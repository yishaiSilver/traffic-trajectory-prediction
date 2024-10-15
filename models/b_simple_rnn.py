"""
This file contains a wrapper for the MLP model. Starting simple.
"""
import numpy as np

import torch
import torch.nn as nn
import torch._dynamo
torch._dynamo.config.suppress_errors = True


from models.layers.mlp import MLP

from utils.logger_config import logger


class SimpleRNN(nn.Module):
    """
    A wrapper for the MLP that .
    """

    def __init__(self, model_config: dict, data_config: dict):
        """
        Constructor for the SimpleMLP class.

        args:
            model_config (dict): dictionary containing the model configuration.
            data_config (dict): dictionary containing the data configuration.
        """

        super().__init__()
        self.device = model_config["device"]

        # want to use an n-dimensional space just in case :)
        coord_dims = data_config["coord_dims"]

        # get the number of outputs the mlp should have
        self.input_timesteps = data_config["input_timesteps"]
        input_size = 0
        self.output_timesteps = data_config["output_timesteps"]
        output_size = coord_dims

        # get the hidden size(s)
        hidden_size = model_config["hidden_size"]
        num_layers = model_config["num_layers"]
        dropout = model_config["dropout"]

        # modify the input size in accordance with the inputs being used
        features = data_config["features"]
        p_in = features["p_in"] + 1  # neighbors plus target
        v_in = features["v_in"]  # v is same # of agents as p
        lane = features["lane"]
        self.positional_embeddings = features["positional_embeddings"]

        input_size += p_in * coord_dims
        input_size += v_in * coord_dims
        input_size += lane * 4  # 4: x, y, dx, dy

        # add the positional embeddings *if* they are being used
        input_size *= (
            self.positional_embeddings * 2 if self.positional_embeddings else 1
        )

        self.input_size = input_size
        self.hidden_size = hidden_size

        # create the recurrent network
        # TODO change to config spec: RNN, GRU, LSTM
        self.rnn = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout,
            batch_first=True,
            device=self.device,
        )
        self.fc = nn.Linear(hidden_size, output_size, device=self.device)

        logger.debug(" Created RNN with input size: %d", input_size)


    @torch.compile()
    def get_positional_embeddings(self, x):
        """
        Get the positional embeddings for the input vector.
        """
        x_positional = torch.zeros(x.shape[0], x.shape[1], 0, device=self.device)
        for i in range(self.positional_embeddings):
            s = torch.sin(2**(i) * np.pi * x)
            c = torch.cos(2**(i) * np.pi * x)

            x_positional = torch.cat((x_positional, s), dim=2)
            x_positional = torch.cat((x_positional, c), dim=2)

        # change to device
        x_positional = x_positional.to(self.device)

        return x_positional

    @torch.compile()
    def forward(self, x):
        """
        Forward pass through the network.
        """
        x = torch.stack(x)  # b x timesteps x features

        # get the positional embeddings
        x = self.get_positional_embeddings(x)

        # initialize the hidden state
        hidden = None

        outputs = []

        for t in range(self.output_timesteps):
            # get the output
            x_t, hidden = self.rnn(x, hidden)

            # get the last output
            x_t = x_t[:, -1, :]
            x_t = self.fc(x_t)

            # append the output
            outputs.append(x_t)

            # add the output to the input, replacing the first element
            x_t = x_t.unsqueeze(1)

            # get the positional embeddings
            x_t = self.get_positional_embeddings(x_t)

            x = torch.cat((x, x_t), dim=1)

            # sliding window approach:
            # x = x[:, 1:, :]

        # stack the outputs
        outputs = torch.stack(outputs, dim=1)

        return outputs