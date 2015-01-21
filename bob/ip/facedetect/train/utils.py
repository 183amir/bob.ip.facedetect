import numpy
import math
import os

from .._library import BoundingBox


available_sources = {
  'direct'        : ('topleft', 'bottomright'),
  'eyes'          : ('leye', 'reye'),
  'left-profile'  : ('eye', 'mouth'),
  'right-profile' : ('eye', 'mouth'),
  'ellipse'       : ('center', 'angle', 'axis_radius')
}

# This struct specifies, which paddings should be applied to which source.
# All values are relative to the inter-node distance
default_paddings = {
  'direct'        : None,
  'eyes'          : {'left' : -1.0, 'right' : +1.0, 'top': -0.7, 'bottom' : 1.7}, # These parameters are used to match Cosmin's implementation (which was buggy...)
  'left-profile'  : {'left' : -0.2, 'right' : +0.8, 'top': -1.0, 'bottom' : 1.0},
  'right-profile' : {'left' : -0.8, 'right' : +0.2, 'top': -1.0, 'bottom' : 1.0},
  'ellipse'       : None
}


def bounding_box_from_annotation(source=None, padding=None, **kwargs):
  """Creates a bounding box from the given parameters.
  If 'sources' are specified, the according keywords (see available_sources) must be given as well.
  Otherwise, the source is estimated from the given keyword parameters if possible.

  If 'topleft' and 'bottomright' are given (i.e., the 'direct' source), they are taken as is.
  Note that the 'bottomright' is NOT included in the bounding box.

  For source 'ellipse', the bounding box is computed to capture the whole ellipse, even if it is rotated.

  For other sources (i.e., 'eyes'), the center of the two given positions is computed, and the 'padding' is applied.
  If 'padding ' is None (the default) then the default_paddings of this source are used instead.
  """

  if source is None:
    # try to estimate the source
    for s,k in available_sources.iteritems():
      # check if the according keyword arguments are given
      if k[0] in kwargs and k[1] in kwargs:
        # check if we already assigned a source before
        if source is not None:
          raise ValueError("The given list of keywords (%s) is ambiguous. Please specify a source" % kwargs)
        # assign source
        source = s

    # check if a source could be estimated from the keywords
    if source is None:
      raise ValueError("The given list of keywords (%s) could not be interpreted" % kwargs)

  assert source in available_sources

  # use default padding if not specified
  if padding is None:
    padding = default_paddings[source]

  keys = available_sources[source]
  if source == 'ellipse':
    # compute the tight bounding box for the ellipse
    angle = kwargs['angle']
    axis = kwargs['axis_radius']
    center = kwargs['center']
    dx = abs(math.cos(angle) * axis[0]) + abs(math.sin(angle) * axis[1])
    dy = abs(math.sin(angle) * axis[0]) + abs(math.cos(angle) * axis[1])
    top = center[0] - dy
    bottom = center[0] + dy
    left = center[1] - dx
    right = center[1] + dx
  elif padding is None:
    # There is no padding to be applied -> take nodes as they are
    top    = kwargs[keys[0]][0]
    bottom = kwargs[keys[1]][0]
    left   = kwargs[keys[0]][1]
    right  = kwargs[keys[1]][1]
  else:
    # apply padding
    pos_0 = kwargs[keys[0]]
    pos_1 = kwargs[keys[1]]
    tb_center = float(pos_0[0] + pos_1[0]) / 2.
    lr_center = float(pos_0[1] + pos_1[1]) / 2.
    distance = math.sqrt((pos_0[0] - pos_1[0])**2 + (pos_0[1] - pos_1[1])**2)

    top    = tb_center + padding['top'] * distance
    bottom = tb_center + padding['bottom'] * distance
    left   = lr_center + padding['left'] * distance
    right  = lr_center + padding['right'] * distance

  return BoundingBox((top, left), (bottom - top, right - left))



def parallel_part(data, parallel):
  """Splits off samples from the the given data list and the given number of parallel jobs based on the SGE_TASK_ID."""
  if parallel is None or "SGE_TASK_ID" not in os.environ:
    return data

  data_per_job = int(math.ceil(float(len(data)) / float(parallel)))
  task_id = int(os.environ['SGE_TASK_ID'])
  first = (task_id-1) * data_per_job
  last = min(len(data), task_id * data_per_job)
  return data[first:last]



def quasi_random_indices(number_of_total_items, number_of_desired_items = None):
  """Returns a quasi-random list of indices that will contain exactly the number of desired indices (or the number of total items in the list, if this is smaller)."""
  # check if we need to compute a sublist at all
  if number_of_desired_items is None or number_of_desired_items >= number_of_total_items or number_of_desired_items < 0:
    return range(number_of_total_items)

  increase = float(number_of_total_items)/float(number_of_desired_items)
  # generate a regular quasi-random index list
  return [int((i +.5)*increase) for i in range(number_of_desired_items)]