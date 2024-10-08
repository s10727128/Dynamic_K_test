r"""
Adaption to act as the MLP layer using an MoE MLP layer in transformer.
"""
import torch
import torch.nn as nn
from .layers import FMoE
from .linear import FMoELinear
from .fastermoe.config import switch_from_env
from typing import Optional

class _Expert(nn.Module):
    r"""
    An expert using 2 FMoELinear modules to speed up the computation of experts
    within one worker.
    """

    def __init__(self, num_expert, d_model, d_hidden, activation, rank=0):
        super().__init__()
        self.htoh4 = FMoELinear(num_expert, d_model, d_hidden, bias=True, rank=rank)
        self.h4toh = FMoELinear(num_expert, d_hidden, d_model, bias=True, rank=rank)
        self.activation = activation

    def forward(self, inp, fwd_expert_count):
        r"""
        First expand input to 4h (the hidden size is variable, but is called h4
        for convenience). Then perform activation. Finally shirink back to h.
        """
        x = self.htoh4(inp, fwd_expert_count)
        x = self.activation(x)
        x = self.h4toh(x, fwd_expert_count)
        return x


class FMoETransformerMLP(FMoE):
    r"""
    A complete MoE MLP module in a Transformer block.
    * `activation` is the activation function to be used in MLP in each expert.
    * `d_hidden` is the dimension of the MLP layer.
    """

    def __init__(
        self,
        num_expert=32,
        d_model=1024,
        d_hidden=4096,
        activation=torch.nn.GELU(),
        world_size=1,
        moe_group=None,
        expert_dp_comm="none",
        expert_rank=0,
        **kwargs
    ):
        def one_expert(d_model):
            return _Expert(1, d_model, d_hidden, activation, rank=0)
        
        expert = one_expert
        # print("moe world size: ", world_size)
        super().__init__(num_expert=num_expert, d_model=d_model, expert=expert, world_size=world_size, moe_group=moe_group, **kwargs)
        self.mark_parallel_comm(expert_dp_comm)

        self.total_experts = num_expert * world_size
        self.top_k = kwargs.get('top_k')

    def forward(self, inp: torch.Tensor, layer_idx = 0,  training_step=0, fuse_token=False, batch_padding_mask=None, 
                last_elements_FFN0=None, last_elements_FFN1=None, last_elements_FFN2=None, last_elements_FFN3=None,
                last_elements_FFN4=None, last_elements_FFN5=None,last_elements_FFN6=None, last_elements_FFN7=None, ema_comparison_masks=None):
                # expert_grads_L0_FFN0_nabs=None, expert_grads_L0_FFN1_nabs=None,
                # expert_grads_L1_FFN0_nabs=None, expert_grads_L1_FFN1_nabs=None):   #Optional[torch.Tensor] = None
        r"""
        This module wraps up the FMoE module with reshape, residual and layer
        normalization.
        """
        # print("change successful: ", fuse_token)\
        # print(batch_padding_mask)
        original_shape = inp.shape
        inp = inp.reshape(-1, self.d_model)
        output, fusion_costs, comm_time, traffic_size = super().forward(inp, original_shape, self.total_experts, self.top_k, 
                                                                        layer_idx = layer_idx, fuse_token=fuse_token, training_step=training_step,
                                                                        batch_padding_mask=batch_padding_mask,
                                                                        last_elements_FFN0=last_elements_FFN0, last_elements_FFN1=last_elements_FFN1,
                                                                        last_elements_FFN2=last_elements_FFN2, last_elements_FFN3=last_elements_FFN3,
                                                                        last_elements_FFN4=last_elements_FFN4, last_elements_FFN5=last_elements_FFN5,
                                                                        last_elements_FFN6=last_elements_FFN6, last_elements_FFN7=last_elements_FFN7,
                                                                        ema_comparison_masks=ema_comparison_masks)
        # return output.reshape(original_shape), fusion_costs, comm_time, traffic_size
        return output.reshape(original_shape), fusion_costs, comm_time
