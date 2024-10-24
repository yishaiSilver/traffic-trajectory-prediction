"""
A module used to generate encodings for a list of lanes.
"""

import torch.nn as nn

from models.lanes.pointnet import PointNet


class LaneEncoder(nn.Module):
    """
    A module that manages how the lanes get encoded.
    """

    def __init__(self, num_points):
        """
        Initializes the LaneEncoder module.
        """
        super().__init__()

        self.angle_filter = True
        self.distance_filter = True
        self.output_size = 128

        self.ortho_lambda = 0.001

        # . TODO will eventually want to use some sort of network
        # to evaluate which lanes are important, but for now the general
        # direction will have to suffice

        # . TODO possibly use zero padding to begin with for optimization

        self.pointnet = PointNet(num_points, 4, self.output_size)  # 4 input dims

    def forward(self, x, lanes):
        """
        Encodes the lanes.

        args:
            x (torch.Tensor): the position of the agent
                batches x timesteps x dims
            lanes (list): the lanes to encode
                list of torch.Tensors: batches x lanes x dims

        returns:
            torch.Tensor: the encoded lanes
                batches x timesteps x encoded_dims
        """

        # since lanes are irrelevant to time, just flatten them into batches
        b, t, p, d = lanes.shape
        lanes = lanes.view(b * t, d, p)  # reordering d and p

        if x.is_cuda:
            lanes = lanes.cuda()

        # track gradients only for the pointnet call
        lanes = lanes.detach()

        # get the embeddings
        embeddings, ortho_loss = self.pointnet(lanes)

        # convert back to batchsize x timesteps x embedddings
        embeddings = embeddings.view(b, t, -1)

        return embeddings, ortho_loss * self.ortho_lambda
