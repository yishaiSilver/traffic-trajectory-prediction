"""

This module contains the `AgentCenter` class which applies agent-centered
transformation to the given batch data.

"""

import numpy as np
import torch


class AgentCenter:
    """
    Applies agent-centered transformation to the given batch_data.

    Methods:
        apply(batch_data):
            Apply agent-centered transformation to the given batch_data.

        invert(batch_data):
            Inverts the position inputs and outputs in the batch data by
            removing the offsets.
    """

    @staticmethod
    def homogenize_matrix(matrix):
        """
        Homogenize a 2D matrix by adding a column of ones.

        Args:
            matrix (np.ndarray): 2D matrix.

        Returns:
            np.ndarray: Homogenized matrix with an additional column of ones.
        """

        # get the original shape
        original_shape = matrix.shape

        # get the non-numerical dimensions
        non_numerical_dims = original_shape[:-1]

        # add the '1' layer/row
        shape = non_numerical_dims + (1,)
        ones = np.ones(shape)

        homogenized_matrix = np.concatenate(
            [matrix, ones],
            axis=-1,
        )
        return homogenized_matrix

    @staticmethod
    def get_rotation_matrix(positions):
        """
        Gets the rotation matrix for the given positions.
        """
        rotation_transforms = np.eye(3)

        # get the angle from the target agent's first input position to the
        # final input position
        first_position = positions[0]
        last_position = positions[-1]

        # get the angle
        theta = (
            -np.arctan2(
                last_position[1] - first_position[1],
                last_position[0] - first_position[0],
            )
            + np.pi / 2
        )

        rotation_transforms[0, 0] = np.cos(theta)
        rotation_transforms[0, 1] = -np.sin(theta)
        rotation_transforms[1, 0] = np.sin(theta)
        rotation_transforms[1, 1] = np.cos(theta)

        return rotation_transforms

    @staticmethod
    def apply(datum):
        """
        Apply agent-centered transformation to the given datum.

        Args:
            datum (dict): Dictionary representing a single data point.

        Returns:
            dict: Transformed datum with updated positions.
        """
        # get all of the ids for the agents being tracked
        # renaming due to bad naming in the dataset
        agent_ids = datum["track_id"]

        # extract the agent_id from the datum
        target_id = datum["agent_id"]

        # get the index of the target agent
        agent_index = np.where(agent_ids == target_id)[0][0]

        # get the lanes and norms for the target agent
        lanes = np.array(datum["lane"])
        lane_norms = np.array(datum["lane_norm"])

        # get the input and output data
        positions = np.array(datum["p_in"])
        velocities = np.array(datum["v_in"])

        # FIXME: 
        # save the cutoff for the input data before we extend it
        input_length = positions.shape[1]

        # extend by the output data
        positions = np.concatenate(
            [positions, np.array(datum["p_out"])], axis=1
        )
        velocities = np.concatenate(
            [velocities, np.array(datum["v_out"])], axis=1
        )

        # get the number of timesteps
        _, num_timesteps, _ = positions.shape

        # homogenize the 2D data
        positions_h = AgentCenter.homogenize_matrix(positions)
        velocities_h = AgentCenter.homogenize_matrix(velocities)
        lanes_h = AgentCenter.homogenize_matrix(lanes)
        lane_norms_h = AgentCenter.homogenize_matrix(lane_norms)

        # create a list of transformation matrices that center all points
        # around the target agent
        translation_transforms = np.eye(3)[np.newaxis].repeat(
            num_timesteps, axis=0
        )

        # get the target agent's positions
        target_positions = positions[agent_index]

        # get the offsets that should be experienced by lanes (which are not
        # updated at every timestamp).
        # needs to be done before centering positions around agent 
        # since diff will be 0 after centering at each timestep
        offsets_h = np.diff(positions_h[agent_index], axis=0)
        first_offset = np.array([0, 0, 0])
        offsets_h = np.vstack([first_offset, offsets_h])

        # set the translation component of the transformation matrices
        translation_transforms[:, :2, 2] -= target_positions

        # apply the translation transformation to all points
        positions_h = np.matmul(
            translation_transforms, positions_h[:, :, :, np.newaxis]
        )

        # get rid of the last dimension
        # FIXME: why does the extra dimension exist?
        positions_h = positions_h[:, :, :, 0]

        # create the rotation transform (key difference: only one needed)
        rotation_transforms = AgentCenter.get_rotation_matrix(
            positions[agent_index]
        )

        # apply the rotation transformation to:
        # positions, velocities, lanes, lane_norms
        positions_h = np.matmul(
            rotation_transforms, positions_h[:, :, :, np.newaxis]
        )
        velocities_h = np.matmul(
            rotation_transforms, velocities_h[:, :, :, np.newaxis]
        )
        lanes_h = np.matmul(
            rotation_transforms, lanes_h[:, :, np.newaxis]
        )
        lane_norms_h = np.matmul(
            rotation_transforms, lane_norms_h[:, :, np.newaxis]
        )
        offsets_h = np.matmul(
            rotation_transforms, offsets_h[:, :, np.newaxis]
        )

        # dehomogenize the data
        positions = positions_h[:, :, :2, 0]
        velocities = velocities_h[:, :, :2, 0]
        lanes = lanes_h[:, :2, 0]  # one less dimension b/c no times
        lane_norms = lane_norms_h[:, :2, 0]
        offsets = offsets_h[:, :2, 0]

        # Update the lane positions for the target agent: don't just want 0s
        positions[agent_index] = offsets

        p_out = positions[:, input_length:]

        # TODO change this to a full revert, rather than just the translated, rotated
        # positions
        # cumsum
        p_out = np.cumsum(p_out, axis=1)

        # update the positions in the datum
        datum["p_in"] = positions[:, :input_length]
        datum["v_in"] = velocities[:, :input_length]
        datum["p_out"] = p_out
        datum["v_out"] = velocities[:, input_length:]

        # update the lane positions
        datum["lane"] = lanes
        datum["lane_norm"] = lane_norms

        # save the prior correction
        # AgentCenter.prior_prediction_correction = datum["prediction_correction"]

        # update the prediction correction
        datum["prediction_correction"] = AgentCenter.inverse

        return datum

    @staticmethod
    def inverse(batch_predictions, batch_metadata):
        """TODO: correct_predictions"""

        # IMPORTANT: inputs are batched

        # NOTE: Since we have only moved the positions, we can just leave them
        # as is for training, but we'll need to revert them back to the original
        # positions when we test against the dataset.

        # Really, this should convert all the way back to the original, global
        # positions, but that's a bit more effor. Leaving it as a TODO for now.
        # thought: embed metadata in the data to know how to invert it:
        # input, output, prediction_correction, batch_correction_metadata.

        # convert displacements to positions by using cumsum
        batch_predictions = torch.cumsum(batch_predictions, axis=1)

        return batch_predictions

        # # apply corrections needed by other transformations.
        # return AgentCenter.prior_prediction_correction(batch_predictions, batch_metadata)
