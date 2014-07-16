
import argparse
import facereclib
import bob
import numpy
import math
import os, sys

from ..detector import Sampler, Cascade
from ..graph import TrainingSet, FaceGraph, ActiveShapeModel, JetStatistics
from .. import BoundingBox, utils

from .train_localizer import ANNOTATION_TYPES


def command_line_options(command_line_arguments):

  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)

  parser.add_argument('--databases', '-d', default=['banca'], nargs='+', help = "Select the databases to get the training images from.")
  parser.add_argument('--annotation-types', '-a', default='eyes', choices=ANNOTATION_TYPES.keys(), help = "Select the types of annotations that you want to train.")

  parser.add_argument('--patch-size', '-p', type=int, nargs=2, default=(96,80), help = "The size of the patch for the image in y and x.")
  parser.add_argument('--offset', '-o', type=int, nargs=2, default=(30,30), help = "The offset at both sides of the detected bounding box to consider")
  parser.add_argument('--distance', '-s', type=int, default=2, help = "The distance with which the image should be scanned.")
  parser.add_argument('--scale-base', '-S', type=float, default = math.pow(2.,-1./8.), help = "The logarithmic distance between two scales (should be between 0 and 1).")
  parser.add_argument('--lowest-scale', '-f', type=float, default = 0.25, help = "Faces which will be lower than the given scale times the image resolution will not be found.")
  parser.add_argument('--similarity-threshold', '-t', type=float, default=0.8, help = "The bounding box overlap thresholds for which positive examples are accepted.")

  parser.add_argument('--cascade-file', '-r', help = "If given, faces detected with the given cascade are used for training the the local model.")
  parser.add_argument('--extracted-training-directory', '-R', default = 'training_set', help = "The directory, where detected training images and according annotations are stored.")

  parser.add_argument('--examples-per-image-scale', '-e', type=int, default = 100, help = "The number of training examples for each image scale.")
  parser.add_argument('--training-examples', '-E', type=int, default = 10000, help = "The number of training examples to sample.")
  parser.add_argument('--limit-training-files', '-y', type=int, help = "Limit the number of training files (for debug purposes only).")
  parser.add_argument('--subspace-size', '-A', type=float, default=0.98, help = "The local model is computed, reducing the subspace dimension to the given total energy.")

  parser.add_argument('--local-model-type', '-T', choices = ("graph", "asm", "stat"), default = "graph", help = "Select the type of local model that you want to train")
  parser.add_argument('--cluster-count', '-C', type=int, help = "If given, the Gabor jets are clustered with K-Means using the given number of means (for 'graph' only).")
  parser.add_argument('--local-patch-size', '-L', type=int, default=21, help = "The size of the local patches for the Active Shape Model.")

  parser.add_argument('--trained-file', '-w', default = 'graphs.hdf5', help = "The file to write the resulting trained localizer into.")

  facereclib.utils.add_logger_command_line_option(parser)
  args = parser.parse_args(command_line_arguments)
  facereclib.utils.set_verbosity_level(args.verbose)

  return args



def main(command_line_arguments = None):
  args = command_line_options(command_line_arguments)

  # get training data
  training_files = utils.training_image_annot(args.databases, args.limit_training_files, ANNOTATION_TYPES[args.annotation_types])

  if args.cascade_file:
    cascade = Cascade(classifier_file=bob.io.HDF5File(args.cascade_file))
    sampler = Sampler(distance=args.distance, scale_factor=args.scale_base, lowest_scale=args.lowest_scale)
    train_set = TrainingSet(sampler, cascade, args.patch_size, args.offset, args.extracted_training_directory)

    facereclib.utils.info("Loading %d training images" % len(training_files))
    i = 1
    all = len(training_files)
    for file_name, annotations, db_file in training_files:
      facereclib.utils.debug("Loading image file '%s' with %d faces" % (file_name, len(annotations)))
      sys.stdout.write("\rProcessing image file %d of %d '%s' " % (i, all, file_name))
      i += 1
      sys.stdout.flush()
      train_set.add_image(file_name, annotations, db_file)
    sys.stdout.write("\n")
    train_images, train_annotations = train_set.get_images_and_annotations(ANNOTATION_TYPES[args.annotation_types])
  else:
    # create the training set
    sampler = Sampler(patch_size=args.patch_size, scale_factor=args.scale_base, lowest_scale=args.lowest_scale, distance=args.distance, similarity_thresholds=(0,args.similarity_threshold), number_of_parallel_threads=1)
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

    train_images, train_annotations = sampler.get_images_and_annotations(args.offset)

  # train the graphs model
  local_model = {
      'graph' : FaceGraph(number_of_means=args.cluster_count, patch_size=args.patch_size, subspace_size=args.subspace_size, offset=args.offset),
      'asm'   : ActiveShapeModel(patch_size=args.patch_size, local_patch_size=(args.local_patch_size,args.local_patch_size), subspace_size=args.subspace_size, offset=args.offset),
      'stat'  : JetStatistics(patch_size=args.patch_size, subspace_size=args.subspace_size, offset=args.offset)
  } [args.local_model_type]

  local_model.train(train_images, train_annotations)
  facereclib.utils.info("Done. Saving trained model to '%s'" % args.trained_file)
  local_model.save(bob.io.HDF5File(args.trained_file, 'w'))
