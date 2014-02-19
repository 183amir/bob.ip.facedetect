
import argparse
import facereclib
import bob
import numpy
import math
import xbob.boosting
import os, sys

from ..detector import Sampler, Bootstrap, save
from .. import BoundingBox, FeatureExtractor, utils


LBP_VARIANTS = {
  'ell'  : {'circular' : True},
  'u2'   : {'uniform' : True},
  'ri'   : {'rotation_invariant' : True},
  'mct'  : {'to_average' : True, 'add_average_bit' : True},
  'tran' : {'elbp_type' : bob.ip.ELBPType.TRANSITIONAL},
  'dir'  : {'elbp_type' : bob.ip.ELBPType.DIRECTION_CODED}
}

def lbp_variant(patch_size, multi_block, variants, overlap, scale, square, sizes):
  """Returns the kwargs that are required for the LBP variant."""
  res = {}
  for t in variants:
    res.update(LBP_VARIANTS[t])
  if scale:
    if multi_block:
      return FeatureExtractor(patch_size = patch_size, extractors = [bob.ip.LBP(8, block_size=(scale,scale), block_overlap=(scale-1, scale-1) if overlap else (0,0), **res)])
    else:
      return FeatureExtractor(patch_size = patch_size, extractors = [bob.ip.LBP(8, radius=scale, **res)])
  else:
    if multi_block:
      return FeatureExtractor(patch_size = patch_size, template = bob.ip.LBP(8, block_size=(1,1), **res), overlap=overlap, square=square, min_size=sizes[0], max_size=sizes[1])
    else:
      return FeatureExtractor(patch_size = patch_size, template = bob.ip.LBP(8, radius=1, **res), square=square, min_size=sizes[0], max_size=sizes[1])


ANNOTATION_TYPES = {
  'eyes' : ['reye', 'leye'],
  'multipie' : ['reye', 'leye', 'reyeo', 'reyei', 'leyei', 'leyeo', 'nose', 'mouthr', 'mouthl', 'lipt', 'lipb', 'chin', 'rbrowo', 'rbrowi', 'lbrowi', 'lbrowo'],

}

def command_line_options(command_line_arguments):

  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)

  parser.add_argument('--databases', '-d', default=['banca'], nargs='+', help = "Select the databases to get the training images from.")
  parser.add_argument('--annotation-types', '-a', default='eyes', choices=ANNOTATION_TYPES.keys(), help = "Select the types of annotations that you want to train.")
  parser.add_argument('--init-with-average', '-i', action='store_true', help = "Initialize the first weak machine with the average (as a heuristic) rather than calculating it?")
  parser.add_argument('--temp-dir', '-T', default='temp', help = "A directory, where temporary files are written to.")

  parser.add_argument('--lbp-multi-block', '-m', action='store_true', help = "If given multi-block LBP features will be extracted (otherwise, it's regular LBP).")
  parser.add_argument('--lbp-variant', '-l', choices=LBP_VARIANTS.keys(), nargs='+', default = ['tran'], help = "Specify, which LBP variant(s) are wanted (ell is not available for MBLPB codes).")
  parser.add_argument('--lbp-overlap', '-o', action='store_true', help = "Specify the overlap of the MBLBP.")
  parser.add_argument('--lbp-scale', '-L', type=int, help = "If given, only a single LBP extractor with the given LBP scale will be extracted, otherwise all possible scales are generated.")
  parser.add_argument('--lbp-square', '-Q', action='store_true', help = "Generate only square feature extractors, and no rectangular ones.")

  parser.add_argument('--parallel', '-P', default=1, type=int, help = "The number of parallel threads to use for feature extraction.")
  parser.add_argument('--features-in-first-round', '-r', default=8, type=int, help = "The number of features to extract in the first bootstrapping round (will be doubled in each bootstrapping round).")
  parser.add_argument('--bootstrapping-rounds', '-R', default=7, type=int, help = "The number of bootstrapping rounds to perform.")
  parser.add_argument('--patch-size', '-p', type=int, nargs=2, default=(96,80), help = "The size of the patch for the image in y and x.")
  parser.add_argument('--distance', '-s', type=int, default=2, help = "The distance with which the image should be scanned.")
  parser.add_argument('--scale-base', '-S', type=float, default=math.pow(2.,-1./8.), help = "The logarithmic distance between two scales (should be between 0 and 1).")
  parser.add_argument('--lowest-scale', '-f', type=float, default=0, help = "Patches which will be lower than the given scale times the image resolution will not be taken into account; if 0. (the default) all patches will be considered.")
  parser.add_argument('--limit-feature-size', '-F', type=int, nargs=2, default=(1,100), help = "Set the lower and upper limit of the feature size.")
  parser.add_argument('--similarity-threshold', '-t', type=float, default=0.8, help = "The bounding box overlap thresholds for which positive examples are accepted.")

  parser.add_argument('--examples-per-image-scale', '-e', type=int, default = 100, help = "The number of training examples for each image scale.")
  parser.add_argument('--training-examples', '-E', type=int, default = 10000, help = "The number of training examples to sample.")
  parser.add_argument('--limit-training-files', '-y', type=int, help = "Limit the number of training files (for debug purposes only).")

  parser.add_argument('--trained-file', '-w', default = 'localizer.hdf5', help = "The file to write the resulting trained localizer into.")

  facereclib.utils.add_logger_command_line_option(parser)
  args = parser.parse_args(command_line_arguments)
  facereclib.utils.set_verbosity_level(args.verbose)

  return args



def main(command_line_arguments = None):
  args = command_line_options(command_line_arguments)

  # get training data
  training_files = utils.training_image_annot(args.databases, args.limit_training_files)

  # create the training set
  sampler = Sampler(patch_size=args.patch_size, scale_factor=args.scale_base, lowest_scale=args.lowest_scale, distance=args.distance, similarity_thresholds=(0,args.similarity_threshold), number_of_parallel_threads=args.parallel)
  preprocessor = facereclib.preprocessing.NullPreprocessor()

  facereclib.utils.info("Loading %d training images" % len(training_files))
  i = 1
  all = len(training_files)
  for file_name, annotations, _ in training_files:
    facereclib.utils.debug("Loading image file '%s' with %d faces" % (file_name, len(annotations)))
    sys.stdout.write("\rProcessing image file %d of %d '%s' " % (i, all, file_name))
    i += 1
    sys.stdout.flush()
    try:
      image = preprocessor(preprocessor.read_original_data(file_name))
      boxes = [utils.bounding_box_from_annotation(**annotation) for annotation in annotations]
      sampler.add_targets(image, boxes, annotations, args.examples_per_image_scale, ANNOTATION_TYPES[args.annotation_types])
    except KeyError as e:
      facereclib.utils.warn("Ignoring file '%s' since the eye annotations are incomplete" % file_name)
    except Exception as e:
      facereclib.utils.error("Couldn't process file '%s': '%s'" % (file_name, e))
      raise
  sys.stdout.write("\n")


  # train the classifier using bootstrapping
  facereclib.utils.info("Extracting training features")
  feature_extractor = lbp_variant([p/4 for p in args.patch_size], args.lbp_multi_block, args.lbp_variant, args.lbp_overlap, args.lbp_scale, args.lbp_square, args.limit_feature_size)

  # create trainer (number of rounds will be set during bootstrapping)
  weak_trainer = xbob.boosting.trainer.LUTTrainer(feature_extractor.number_of_labels, feature_extractor.number_of_features, len(ANNOTATION_TYPES[args.annotation_types])*2, 'independent')
  trainer = xbob.boosting.trainer.Boosting(weak_trainer, xbob.boosting.loss.JesorskyLoss(), 0)
  bootstrapping = Bootstrap(number_of_rounds=args.bootstrapping_rounds, number_of_weak_learners_in_first_round=args.features_in_first_round, number_of_positive_examples_per_round=args.training_examples, number_of_negative_examples_per_round=0, init_with_average=args.init_with_average)

  # perform the bootstrapping
  classifier, mean, variance, feature_extractor = bootstrapping.coarse_to_fine_feature_selection(trainer, sampler, feature_extractor, filename=os.path.join(args.temp_dir, args.trained_file))

  # write the machine and the feature extractor into the same HDF5 file
  save(args.trained_file, classifier, feature_extractor, mean, variance)
  facereclib.utils.info("Saved bootstrapped classifier to file '%s'" % args.trained_file)
