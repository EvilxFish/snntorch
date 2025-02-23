from .neurons import _SpikeTensor, _SpikeTorchConv, LIF


class Leaky(LIF):
    """
    First-order leaky integrate-and-fire neuron model.
    Input is assumed to be a current injection.
    Membrane potential decays exponentially with rate beta.
    For :math:`U[T] > U_{\\rm thr} ⇒ S[T+1] = 1`.

    If `reset_mechanism = "subtract"`, then :math:`U[t+1]` will have
    `threshold` subtracted from it whenever the neuron emits a spike:

    .. math::

            U[t+1] = βU[t] + I_{\\rm in}[t+1] - RU_{\\rm thr}

    If `reset_mechanism = "zero"`, then :math:`U[t+1]` will be set to `0`
    whenever the neuron emits a spike:

    .. math::

            U[t+1] = βU[t] + I_{\\rm syn}[t+1] - R(βU[t] + I_{\\rm in}[t+1])

    * :math:`I_{\\rm in}` - Input current
    * :math:`U` - Membrane potential
    * :math:`U_{\\rm thr}` - Membrane threshold
    * :math:`R` - Reset mechanism: if active, :math:`R = 1`, otherwise
    :math:`R = 0`
    * :math:`β` - Membrane potential decay rate

    Example::

        import torch
        import torch.nn as nn
        import snntorch as snn

        beta = 0.5

        # Define Network
        class Net(nn.Module):
            def __init__(self):
                super().__init__()

                # initialize layers
                self.fc1 = nn.Linear(num_inputs, num_hidden)
                self.lif1 = snn.Leaky(beta=beta)
                self.fc2 = nn.Linear(num_hidden, num_outputs)
                self.lif2 = snn.Leaky(beta=beta)

            def forward(self, x, mem1, spk1, mem2):
                cur1 = self.fc1(x)
                spk1, mem1 = self.lif1(cur1, mem1)
                cur2 = self.fc2(spk1)
                spk2, mem2 = self.lif2(cur2, mem2)
                return mem1, spk1, mem2, spk2


    :param beta: membrane potential decay rate. Clipped between 0 and 1
    during the forward-pass. May be a single-valued tensor (i.e., equal
    decay rate for all neurons in a layer), or multi-valued (one weight per
    neuron).
    :type beta: float or torch.tensor

    :param threshold: Threshold for :math:`mem` to reach in order to
    generate a spike `S=1`. Defaults to 1
    :type threshold: float, optional

    :param spike_grad: Surrogate gradient for the term dS/dU. Defaults to
    None (corresponds to Heaviside surrogate gradient. See
    `snntorch.surrogate` for more options)
    :type spike_grad: surrogate gradient function from snntorch.surrogate,
    optional

    :param init_hidden: Instantiates state variables as instance variables.
    Defaults to False
    :type init_hidden: bool, optional

    :param inhibition: If `True`, suppresses all spiking other than the
    neuron with the highest state. Defaults to False
    :type inhibition: bool, optional

    :param learn_beta: Option to enable learnable beta. Defaults to False
    :type learn_beta: bool, optional

    :param learn_threshold: Option to enable learnable threshold. Defaults
    to False
    :type learn_threshold: bool, optional

    :param reset_mechanism: Defines the reset mechanism applied to
    :math:`mem` each time the threshold is met. Reset-by-subtraction:
    "subtract", reset-to-zero: "zero, none: "none". Defaults to "subtract"
    :type reset_mechanism: str, optional

    :param state_quant: If specified, hidden state :math:`mem` is quantized
    to a valid state for the forward pass. Defaults to False
    :type state_quant: quantization function from snntorch.quant, optional

    :param output: If `True` as well as `init_hidden=True`, states are
    returned when neuron is called. Defaults to False
    :type output: bool, optional


    Inputs: \\input_, mem_0
        - **input_** of shape `(batch, input_size)`: tensor containing input
        features
        - **mem_0** of shape `(batch, input_size)`: tensor containing the
        initial membrane potential for each element in the batch.

    Outputs: spk, syn_1, mem_1
        - **spk** of shape `(batch, input_size)`: tensor containing the
        output spikes.
        - **mem_1** of shape `(batch, input_size)`: tensor containing the
        next membrane potential for each element in the batch

    Learnable Parameters:
        - **Leaky.beta** (torch.Tensor) - optional learnable weights must be
        manually passed in, of shape `1` or (input_size).
        - **Leaky.threshold** (torch.Tensor) - optional learnable thresholds
        must be manually passed in, of shape `1` or`` (input_size).

    """

    def __init__(
        self,
        beta,
        threshold=1.0,
        spike_grad=None,
        init_hidden=False,
        inhibition=False,
        learn_beta=False,
        learn_threshold=False,
        reset_mechanism="subtract",
        state_quant=False,
        output=False,
    ):
        super(Leaky, self).__init__(
            beta,
            threshold,
            spike_grad,
            init_hidden,
            inhibition,
            learn_beta,
            learn_threshold,
            reset_mechanism,
            state_quant,
            output,
        )

        if self.init_hidden:
            self.mem = self.init_leaky()

    def forward(self, input_, mem=False):

        if hasattr(mem, "init_flag"):  # only triggered on first-pass
            mem = _SpikeTorchConv(mem, input_=input_)
        elif mem is False and hasattr(
            self.mem, "init_flag"
        ):  # init_hidden case
            self.mem = _SpikeTorchConv(self.mem, input_=input_)

        # TO-DO: alternatively, we could do torch.exp(-1 /
        # self.beta.clamp_min(0)),
        # giving actual time constants instead of values in [0, 1] as
        # initial beta
        # beta = self.beta.clamp(0, 1)

        if not self.init_hidden:
            self.reset = self.mem_reset(mem)
            mem = self._build_state_function(input_, mem)

            if self.state_quant:
                mem = self.state_quant(mem)

            if self.inhibition:
                spk = self.fire_inhibition(mem.size(0), mem)  # batch_size
            else:
                spk = self.fire(mem)

            return spk, mem

        # intended for truncated-BPTT where instance variables are hidden
        # states
        if self.init_hidden:
            self._leaky_forward_cases(mem)
            self.reset = self.mem_reset(self.mem)
            self.mem = self._build_state_function_hidden(input_)

            if self.state_quant:
                self.mem = self.state_quant(self.mem)

            if self.inhibition:
                self.spk = self.fire_inhibition(self.mem.size(0), self.mem)
            else:
                self.spk = self.fire(self.mem)

            if self.output:  # read-out layer returns output+states
                return self.spk, self.mem
            else:  # hidden layer e.g., in nn.Sequential, only returns output
                return self.spk

    def _base_state_function(self, input_, mem):
        base_fn = self.beta.clamp(0, 1) * mem + input_
        return base_fn

    def _build_state_function(self, input_, mem):
        if self.reset_mechanism_val == 0:  # reset by subtraction
            state_fn = self._base_state_function(
                input_, mem - self.reset * self.threshold
            )
        elif self.reset_mechanism_val == 1:  # reset to zero
            state_fn = self._base_state_function(
                input_, mem
            ) - self.reset * self._base_state_function(input_, mem)
        elif self.reset_mechanism_val == 2:  # no reset, pure integration
            state_fn = self._base_state_function(input_, mem)
        return state_fn

    def _base_state_function_hidden(self, input_):
        base_fn = self.beta.clamp(0, 1) * self.mem + input_
        return base_fn

    def _build_state_function_hidden(self, input_):
        if self.reset_mechanism_val == 0:  # reset by subtraction
            state_fn = (
                self._base_state_function_hidden(input_)
                - self.reset * self.threshold
            )
        elif self.reset_mechanism_val == 1:  # reset to zero
            self.mem = (1-self.reset) * self.mem
            state_fn = self._base_state_function_hidden(input_)
        elif self.reset_mechanism_val == 2:  # no reset, pure integration
            state_fn = self._base_state_function_hidden(input_)
        return state_fn

    def _leaky_forward_cases(self, mem):
        if mem is not False:
            raise TypeError(
                "When `init_hidden=True`, Leaky expects 1 input argument."
            )

    @classmethod
    def detach_hidden(cls):
        """Returns the hidden states, detached from the current graph.
        Intended for use in truncated backpropagation through time where
        hidden state variables are instance variables."""

        for layer in range(len(cls.instances)):
            if isinstance(cls.instances[layer], Leaky):
                cls.instances[layer].mem.detach_()

    @classmethod
    def reset_hidden(cls):
        """Used to clear hidden state variables to zero.
        Intended for use where hidden state variables are instance variables.
        Assumes hidden states have a batch dimension already."""
        for layer in range(len(cls.instances)):
            if isinstance(cls.instances[layer], Leaky):
                cls.instances[layer].mem = _SpikeTensor(init_flag=False)
