# -*- encoding: utf-8 -*-
import json
import logging

import click


from strephit.commons.classification import reverse_gazetteer
from sklearn.externals import joblib
from sklearn.svm import LinearSVC
from strephit.classification.feature_extractors import FactExtractorFeatureExtractor

logger = logging.getLogger(__name__)


@click.command()
@click.argument('training-set', type=click.File('r'))
@click.argument('language')
@click.option('-o', '--outfile', type=click.Path(dir_okay=False, writable=True),
              default='output/classifier_model.pkl', help='Where to save the model')
@click.option('-c', default=1.0, help='Penalty parameter C of the error term.')
@click.option('--loss', default='squared_hinge', help='Specifies the loss function.',
              type=click.Choice(['hinge', 'squared_hinge']))
@click.option('--penalty', default='l2', help='Specifies the norm used in the penalization.',
              type=click.Choice(['l1', 'l2']))
@click.option('--dual', is_flag=True,
              help='Select the algorithm to either solve the dual or primal optimization problem.')
@click.option('--tol', default=1e-4, help='Tolerance for stopping criteria.')
@click.option('--multi-class', default='ovr', type=click.Choice(['ovr', 'crammer_singer']),
              help='Determines the multi-class strategy.')
@click.option('-v', '--verbose', is_flag=True)
@click.option('--random-state', default=None, type=click.INT,
              help='The seed of the pseudo random number generator to use when shuffling the data.')
@click.option('--max-iter', default=1000, help='The maximum number of iterations to be run.')
@click.option('--gazetteer', type=click.File('r'))
def main(training_set, language, outfile, gazetteer, **kwargs):
    """ Trains the classifier """

    gazetteer = reverse_gazetteer(json.load(gazetteer)) if gazetteer else {}
    extractor = FactExtractorFeatureExtractor(language)

    logger.info("Building training set from '%s' ..." % training_set.name)
    for row in training_set:
        data = json.loads(row)
        extractor.process_sentence(data['sentence'], data['fes'],
                                   add_unknown=True, gazetteer=gazetteer)

    logger.info('Finalizing training set ...')
    x, y = extractor.get_features()

    logger.info('Got %d samples with %d features each', *x.shape)

    logger.info('Fitting model ...')
    kwargs['C'] = kwargs.pop('c')
    svc = LinearSVC(**kwargs)
    svc.fit(x, y)

    joblib.dump((svc, extractor), outfile)
    logger.info("Done, dumped model to '%s'", outfile)
