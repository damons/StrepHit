#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from __future__ import absolute_import

import json
import logging
from sys import exit

import click
import treetaggerwrapper
from treetaggerpoll import TaggerProcessPoll
from treetaggerwrapper import make_tags, NotTag, TreeTagger
from nltk import pos_tag, word_tokenize, pos_tag_sents

from strephit.commons.io import load_scraped_items
from strephit.commons.tokenize import Tokenizer

logger = logging.getLogger(__name__)
treetaggerwrapper.logger.setLevel(logging.WARN)  # they are too verbose


class NLTKPosTagger(object):
    """part-of-speech tagger implemented using the NLTK library"""

    def __init__(self, language):
        self.language = language

    def tag_many(self, documents, tagset=None, **kwargs):
        """ POS-Tag many documents. """
        return pos_tag_sents((word_tokenize(d) for d in documents), tagset)

    def tag_one(self, text, tagset, **kwargs):
        """ POS-Tags the given text """
        return pos_tag(word_tokenize(text, tagset))


class TTPosTagger(object):
    """ part-of-speech tagger implemented using tree tagger and treetaggerwrapper """

    def __init__(self, language, tt_home=None, **kwargs):
        self.language = language
        self.tt_home = tt_home
        self.tokenizer = Tokenizer(language)
        self.tagger = TreeTagger(
            TAGLANG=language,
            TAGDIR=tt_home,
            # Explicit TAGOPT: the default has the '-no-unknown' option,
            # which prints the token rather than '<unknown>' for unknown lemmas
            # We'd rather skip unknown lemmas, as they are likely to be wrong tags
            TAGOPT=u'-token -lemma -sgml -quiet',
            # Use our tokenization logic (CHUNKERPROC here)
            CHUNKERPROC=self._tokenizer_wrapper,
            **kwargs
        )

    def _tokenizer_wrapper(self, tagger, text_list):
        """ Wrap the tokenization logic with the signature required by the TreeTagger CHUNKERPROC kwarg
        """
        tokens = []
        for text in text_list:
            for token in self.tokenizer.tokenize(text):
                tokens.append(token)
        return tokens

    def _postprocess_tags(self, tags, skip_unknown=True):
        """ Clean tagged data from non-tags and unknown lemmas (optionally) """
        clean_tags = []
        for tag in tags:
            if skip_unknown and isinstance(tag, NotTag) or tag.lemma == u'<unknown>':
                logger.debug("Unknown lemma found: %s. Skipping ..." % repr(tag))
                continue
            clean_tags.append(tag)
        return clean_tags

    def tokenize(self, text):
        """ Splits a text into tokens
        """
        return self.tokenizer.tokenize(text)

    def tag_one(self, text, skip_unknown=True, **kwargs):
        """ POS-Tags the given text, optionally skipping unknown lemmas

            :param unicode text: Text to be tagged
            :param bool skip_unknown: Automatically emove unrecognized tags from the result

            Sample usage:

            >>> from strephit.commons.pos_tag import TTPosTagger
            >>> from pprint import pprint
            >>> pprint(TTPosTagger('en').tag_one(u'sample sentence to be tagged fycgvkuhbj'))
            [Tag(word=u'sample', pos=u'NN', lemma=u'sample'),
             Tag(word=u'sentence', pos=u'NN', lemma=u'sentence'),
             Tag(word=u'to', pos=u'TO', lemma=u'to'),
             Tag(word=u'be', pos=u'VB', lemma=u'be'),
             Tag(word=u'tagged', pos=u'VVN', lemma=u'tag')]
        """
        return self._postprocess_tags(make_tags(self.tagger.tag_text(text, **kwargs)),
                                      skip_unknown)

    def tag_many(self, items, document_key, pos_tag_key, batch_size=10000, **kwargs):
        """ POS-Tags many text documents of the given items. Use this for massive text tagging

            :param items: Iterable of items to tag. Generator preferred
            :param document_key: Where to find the text to tag inside each item. Text must be unicode
            :param pos_tag_key: Where to put pos tagged text

            Sample usage:

            >>> from strephit.commons.pos_tag import TTPosTagger
            >>> from pprint import pprint
            >>> pprint(list(TTPosTagger('en').tag_many(
            ...     [{'text': u'Item one is in first position'}, {'text': u'In the second position is item two'}],
            ...     'text', 'tagged'
            ... )))
            [{'tagged': [Tag(word=u'Item', pos=u'NN', lemma=u'item'),
                         Tag(word=u'one', pos=u'CD', lemma=u'one'),
                         Tag(word=u'is', pos=u'VBZ', lemma=u'be'),
                         Tag(word=u'in', pos=u'IN', lemma=u'in'),
                         Tag(word=u'first', pos=u'JJ', lemma=u'first'),
                         Tag(word=u'position', pos=u'NN', lemma=u'position')],
              'text': u'Item one is in first position'},
             {'tagged': [Tag(word=u'In', pos=u'IN', lemma=u'in'),
                         Tag(word=u'the', pos=u'DT', lemma=u'the'),
                         Tag(word=u'second', pos=u'JJ', lemma=u'second'),
                         Tag(word=u'position', pos=u'NN', lemma=u'position'),
                         Tag(word=u'is', pos=u'VBZ', lemma=u'be'),
                         Tag(word=u'item', pos=u'RB', lemma=u'item'),
                         Tag(word=u'two', pos=u'CD', lemma=u'two')],
              'text': u'In the second position is item two'}]
        """
        tt_pool = TaggerProcessPoll(
            TAGLANG=self.language,
            TAGDIR=self.tt_home,
            TAGOPT=u'-token -lemma -sgml -quiet',
            CHUNKERPROC=self._tokenizer_wrapper
        )
        logging.getLogger('TreeTagger').setLevel(logging.WARNING)
        try:
            jobs = []
            for i, item in enumerate(items):
                if not item.get(document_key):
                    continue

                jobs.append((item, tt_pool.tag_text_async(item[document_key], **kwargs)))
                if i % batch_size == 0:
                    for each in self._finalize_batch(jobs, pos_tag_key):
                        yield each
                    jobs = []
            for each in self._finalize_batch(jobs, pos_tag_key):
                yield each
        finally:
            tt_pool.stop_poll()

    def _finalize_batch(self, jobs, pos_tag_key):
        for item, job in jobs:
            job.wait_finished()
            item[pos_tag_key] = self._postprocess_tags(make_tags(job.result))
            yield item


def get_pos_tagger(language, **kwargs):
    """ Returns an initialized instance of the preferred POS tagger for the given language """
    return TTPosTagger(language, **kwargs)


@click.command()
@click.argument('corpus', type=click.Path(exists=True, file_okay=True, resolve_path=True))
@click.argument('document-key')
@click.argument('language-code')
@click.option('-t', '--tagger', type=click.Choice(['tt', 'nltk']), default='tt')
@click.option('-o', '--outfile', type=click.File('w'), default='output/pos_tagged.jsonlines')
@click.option('-T', '--pos-tag-key', default='pos_tag')
@click.option('--tt-home', type=click.Path(exists=True, resolve_path=True),
              help="home directory for TreeTagger")
@click.option('--batch-size', '-b', default=10000)
def main(corpus, document_key, pos_tag_key, language_code, tagger, outfile, tt_home, batch_size):
    """ Perform part-of-speech (POS) tagging over an input corpus.
    """
    if tagger == 'tt':
        pos_tagger = TTPosTagger(language_code, tt_home)
        logger.info("About to perform part-of-speech tagging with TreeTagger ...")
    else:
        pos_tagger = NLTKPosTagger(language_code)
        logger.info("About to perform part-of-speech tagging with NLTK tagger ...")

    corpus = load_scraped_items(corpus)
    
    total = 0
    for i, tagged_document in enumerate(pos_tagger.tag_many(corpus, document_key, pos_tag_key, batch_size)):
        total += 1
        outfile.write(json.dumps(tagged_document) + '\n')
        if (i + 1) % 10000 == 0:
            logger.info('processed %d items', i + 1)
    
    logger.info("Done, total tagged items: %d" % total)
    
    return 0


if __name__ == '__main__':
    exit(main())
