# Copyright (C) 2014 Daniel Lee <lee.daniel.1986@gmail.com>
#
# This file is part of StereoVision.
#
# StereoVision is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# StereoVision is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with StereoVision.  If not, see <http://www.gnu.org/licenses/>.

"""
Utilities for easing user interaction with the ``stereovision`` package.

Variables:

    * ``CHESSBOARD_ARGUMENTS`` - ``argparse.ArgumentParser`` for working with
      chessboards
    * ``STEREO_BM_FLAG`` - ``argparse.ArgumentParser`` for using StereoBM

Functions:

    * ``find_files`` - Discover stereo images in directory
    * ``calibrate_folder`` - Calibrate chessboard images discoverd in a folder

Classes:

    * ``BMTuner`` - Tune block matching algorithm to camera pair

.. image:: classes_ui_utils.svg
"""

from argparse import ArgumentParser
from functools import partial
import os

import cv2
from progressbar import ProgressBar, Percentage, Bar
from stereovision.calibration import StereoCalibrator
from stereovision.exceptions import BadBlockMatcherArgumentError, ChessboardNotFoundError

#: Command line arguments for collecting information about chessboards
import numpy

CHESSBOARD_ARGUMENTS = ArgumentParser(add_help=False)
CHESSBOARD_ARGUMENTS.add_argument("--rows", type=int,
                                  help="Number of inside corners in the "
                                  "chessboard's rows.", default=9)
CHESSBOARD_ARGUMENTS.add_argument("--columns", type=int,
                                  help="Number of inside corners in the "
                                  "chessboard's columns.", default=6)
CHESSBOARD_ARGUMENTS.add_argument("--square-size", help="Size of chessboard "
                                  "squares in cm.", type=float, default=1.8)


#: Command line arguments for using StereoBM rather than StereoSGBM
STEREO_BM_FLAG = ArgumentParser(add_help=False)
STEREO_BM_FLAG.add_argument("--use_stereobm", help="Use StereoBM rather than "
                              "StereoSGBM block matcher.", action="store_true")


def find_files(folder):
    """Discover stereo photos and return them as a pairwise sorted list."""
    files = [i for i in os.listdir(folder) if i.startswith("left")]
    files.sort()
    for i in range(len(files)):
        insert_string = "right{}".format(files[i * 2][4:])
        files.insert(i * 2 + 1, insert_string)
    files = [os.path.join(folder, filename) for filename in files]
    return files


def calibrate_folder(args):
    """
    Calibrate camera based on chessboard images, write results to output folder.

    All images are read from disk. Chessboard points are found and used to
    calibrate the stereo pair. Finally, the calibration is written to the folder
    specified in ``args``.

    ``args`` needs to contain the following fields:
        input_files: List of paths to input files
        rows: Number of rows in chessboard
        columns: Number of columns in chessboard
        square_size: Size of chessboard squares in cm
        output_folder: Folder to write calibration to
    """
    height, width = cv2.imread(args.input_files[0]).shape[:2]
    calibrator = StereoCalibrator(args.rows, args.columns, args.square_size,
                                  (width, height))
    progress = ProgressBar(maxval=len(args.input_files),
                          widgets=[Bar("=", "[", "]"),
                          " ", Percentage()])
    print("Reading input files...")
    progress.start()
    while args.input_files:
        left, right = args.input_files[:2]
        img_left, im_right = cv2.imread(left), cv2.imread(right)
        try:
            calibrator.add_corners((img_left, im_right),
                                   show_results=args.show_chessboards)
        except ChessboardNotFoundError:
            print "Error with %s,%s" % (left, right)
        args.input_files = args.input_files[2:]
        progress.update(progress.maxval - len(args.input_files))

    progress.finish()
    print("Calibrating cameras. This can take a while.")
    calibration = calibrator.calibrate_cameras()
    avg_error, ocv_error = calibrator.check_calibration(calibration)
    print("The average error between chessboard points and their epipolar "
          "lines is \n"
          "{} pixels. This should be as small as possible.\n"
          "Opencv reported errror is {}".format(avg_error, ocv_error))
    calibration.export(args.output_folder, avg_error, ocv_error)


class BMTuner(object):

    """
    A class for tuning Stereo BM settings.

    Display a normalized disparity picture from two pictures captured with a
    ``CalibratedPair`` and allow the user to manually tune the settings for the
    ``BlockMatcher``.

    The settable parameters are intelligently read from the ``BlockMatcher``,
    relying on the ``BlockMatcher`` exposing them as ``parameter_maxima``.
    """

    #: Window to show results in
    window_name = "BM Tuner"

    def _set_value_from_trackbar(self, parameter, constraint, new_trackbar_value):
        new_value = constraint.actual_value(new_trackbar_value)
        self._set_value(parameter, new_value)

    def _set_value(self, parameter, new_value):
        """Try setting new parameter on ``block_matcher`` and update map."""
        try:
            self.block_matcher.__setattr__(parameter, new_value)
        except BadBlockMatcherArgumentError as e:
            print e
            return
        self._update_disparity_map_no_wait()

    def _initialize_trackbars(self):
        """
        Initialize trackbars by discovering ``block_matcher``'s parameters.
        """
        def setMaxDepth(v):
            self.rendermaxdepth = v
        cv2.createTrackbar(
            "maxdepth",
            self.window_name,
            1,
            100,
            setMaxDepth)

        for parameter in self.block_matcher.parameter_names():
            if parameter in self.block_matcher.parameter_constraints:
                constraint = self.block_matcher.parameter_constraints[parameter]
                trackbar_name = constraint.trackbar_name(parameter)
                param_value = self.block_matcher.__getattribute__(parameter)
                cv2.createTrackbar(
                    trackbar_name,
                    self.window_name,
                    constraint.trackbar_value(param_value),
                    constraint.trackbar_max(),
                    partial(self._set_value_from_trackbar, parameter, constraint))
            else:
                maximum = self.block_matcher.parameter_maxima[parameter]
                if not maximum:
                    maximum = self.shortest_dimension
                cv2.createTrackbar(parameter, self.window_name,
                                   self.block_matcher.__getattribute__(parameter),
                                   maximum,
                                   partial(self._set_value, parameter))

    def _save_bm_state(self):
        """Save current state of ``block_matcher``."""
        for parameter in self.block_matcher.parameter_names():
            self.bm_settings[parameter].append(
                               self.block_matcher.__getattribute__(parameter))

    def __init__(self, block_matcher, calibration, image_pair, show_sources=False, time_smoothing_window=1):
        """
        Initialize tuner window and tune given pair.

        ``block_matcher`` is a ``BlockMatcher``, ``calibration`` is a
        ``StereoCalibration`` and ``image_pair`` is a rectified image pair.
        """
        #: Stereo calibration to find Stereo BM settings for
        self.calibration = calibration
        #: (left, right) image pair to find disparity between
        self.pair = image_pair
        #: Block matcher to be tuned
        self.block_matcher = block_matcher
        #: Shortest dimension of image
        self.shortest_dimension = min(self.pair[0].shape[:2])
        #: Settings chosen for ``BlockMatcher``
        self.bm_settings = {}
        for parameter in self.block_matcher.parameter_names():
            self.bm_settings[parameter] = []
        cv2.namedWindow(self.window_name)
        self._initialize_trackbars()
        self.show_sources = show_sources
        self.rendermaxdepth = 10

        self.time_smoothing_window = time_smoothing_window
        self.last_disparities = [(None, None)] * time_smoothing_window
        self.next_disparity_index = 0
        self.accepted_deviation = 10

    def _update_disparity_map_no_wait(self):
        """
        Update disparity map in GUI.

        The disparity image is normalized to the range 0-255 and then divided by
        255, because OpenCV multiplies it by 255 when displaying. This is
        because the pixels are stored as floating points.
        """
        disparity = self.block_matcher.get_disparity(self.pair)
        validity_threshold = self.block_matcher.minDisparity - 1 + numpy.finfo(numpy.float32).eps
        validity_bool = disparity > validity_threshold
        validity_int = (validity_bool * 255).astype(numpy.uint8)
        validity_3int = cv2.cvtColor(validity_int, cv2.COLOR_GRAY2BGR)

        colored_disparity = self._color_disparity(disparity)
        colored_disparity = cv2.bitwise_and(colored_disparity, validity_3int)
        display = colored_disparity

        if self.show_sources:

            display = numpy.concatenate((self.pair[0], display), axis=1)
            display = numpy.concatenate((display, self.pair[1]), axis=1)

        self.last_disparities[self.next_disparity_index] = (disparity, validity_bool)
        self.next_disparity_index = (self.next_disparity_index + 1) % self.time_smoothing_window

        if self.time_smoothing_window > 1:
            smoothed, validity = self._get_smoothed_disparity()
            validity_int = (validity_bool * 255).astype(numpy.uint8)
            validity_3int = cv2.cvtColor(validity_int, cv2.COLOR_GRAY2BGR)
            colored_smoothed = self._color_disparity(smoothed)
            colored_smoothed = cv2.bitwise_and(colored_smoothed, validity_3int)

            padding = numpy.zeros((self.pair[0].shape[0], self.pair[0].shape[1], 3), numpy.uint8)
            if self.show_sources:
                padded = numpy.concatenate((padding, colored_smoothed, padding), axis=1)
            else:
                padded = colored_smoothed
            display = numpy.concatenate((display, padded), axis=0)
            self.disparity = smoothed
            self.validity = validity
        else:
            self.disparity = disparity
            self.validity = validity_bool

        cv2.imshow(self.window_name, display)

    def _update_disparity_map_and_wait(self):
        self._update_disparity_map_no_wait()
        cv2.waitKey()

    def _color_disparity(self, disparity):
        disparity_min = self.block_matcher.minDisparity
        disparity_range = self.block_matcher.numDisparities - 1
        norm_coeff = 255. / disparity_range
        corrected_disparity = ((disparity - disparity_min) * norm_coeff)
        corrected_disparity = numpy.clip(corrected_disparity, 0, 255).astype(numpy.uint8)
        return cv2.applyColorMap(corrected_disparity, cv2.COLORMAP_JET)

    def _get_smoothed_disparity(self):
        validities = [v for d, v in self.last_disparities if d is not None]
        validity = reduce(numpy.logical_and, validities)
        disparities = [d for d, v in self.last_disparities if d is not None]
        deviation = numpy.std(disparities, axis=0)
        deviation_validity = deviation < self.accepted_deviation
        validity = numpy.logical_and(validity, deviation_validity)
        mean = numpy.mean(disparities, axis=0)
        return mean, validity

    def tune_pair(self, pair, wait_key=True):
        """Tune a pair of images."""
        self._save_bm_state()
        self.pair = pair
        if wait_key:
            self._update_disparity_map_and_wait()
        else:
            self._update_disparity_map_no_wait()

    def report_settings(self, parameter):
        """
        Report chosen settings for ``parameter`` in ``block_matcher``.

        ``bm_settings`` is updated to include the latest state before work is
        begun. This state is removed at the end so that the method has no side
        effects. All settings are reported except for the first one on record,
        which is ``block_matcher``'s default setting.
        """
        self._save_bm_state()
        report = []
        settings_list = self.bm_settings[parameter][1:]
        unique_values = list(set(settings_list))
        value_frequency = {}
        for value in unique_values:
            value_frequency[settings_list.count(value)] = value
        frequencies = value_frequency.keys()
        frequencies.sort(reverse=True)
        header = "{} value | Selection frequency".format(parameter)
        left_column_width = len(header[:-21])
        right_column_width = 21
        report.append(header)
        report.append("{}|{}".format("-" * left_column_width,
                                    "-" * right_column_width))
        for frequency in frequencies:
            left_column = str(value_frequency[frequency]).center(
                                                             left_column_width)
            right_column = str(frequency).center(right_column_width)
            report.append("{}|{}".format(left_column, right_column))
        # Remove newest settings
        for param in self.block_matcher.parameter_names():
            self.bm_settings[param].pop(-1)
        return "\n".join(report)
