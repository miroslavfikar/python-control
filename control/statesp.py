"""statesp.py

State space representation and functions.

This file contains the StateSpace class, which is used to represent linear
systems in state space.  This is the primary representation for the
python-control library.

"""

# Python 3 compatibility (needs to go here)
from __future__ import print_function
from __future__ import division         # for _convert_to_statespace

"""Copyright (c) 2010 by California Institute of Technology
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.

3. Neither the name of the California Institute of Technology nor
   the names of its contributors may be used to endorse or promote
   products derived from this software without specific prior
   written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
FOR A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL CALTECH
OR THE CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.

Author: Richard M. Murray
Date: 24 May 09
Revised: Kevin K. Chen, Dec 10

$Id$
"""

import math
import numpy as np
from numpy import any, array, asarray, concatenate, cos, delete, \
    dot, empty, exp, eye, isinf, ones, pad, sin, zeros, squeeze, pi
from numpy.random import rand, randn
from numpy.linalg import solve, eigvals, matrix_rank
from numpy.linalg.linalg import LinAlgError
import scipy as sp
from scipy.signal import cont2discrete
from scipy.signal import StateSpace as signalStateSpace
from warnings import warn
from .lti import LTI, common_timebase, isdtime, _process_frequency_response
from . import config
from copy import deepcopy

__all__ = ['StateSpace', 'ss', 'rss', 'drss', 'tf2ss', 'ssdata']


# Define module default parameter values
_statesp_defaults = {
    'statesp.use_numpy_matrix': False,  # False is default in 0.9.0 and above
    'statesp.remove_useless_states': False,
    'statesp.latex_num_format': '.3g',
    'statesp.latex_repr_type': 'partitioned',
    }


def _ssmatrix(data, axis=1):
    """Convert argument to a (possibly empty) 2D state space matrix.

    The axis keyword argument makes it convenient to specify that if the input
    is a vector, it is a row (axis=1) or column (axis=0) vector.

    Parameters
    ----------
    data : array, list, or string
        Input data defining the contents of the 2D array
    axis : 0 or 1
        If input data is 1D, which axis to use for return object.  The default
        is 1, corresponding to a row matrix.

    Returns
    -------
    arr : 2D array, with shape (0, 0) if a is empty

    """
    # Convert the data into an array or matrix, as configured
    # If data is passed as a string, use (deprecated?) matrix constructor
    if config.defaults['statesp.use_numpy_matrix']:
        arr = np.matrix(data, dtype=float)
    elif isinstance(data, str):
        arr = np.array(np.matrix(data, dtype=float))
    else:
        arr = np.array(data, dtype=float)
    ndim = arr.ndim
    shape = arr.shape

    # Change the shape of the array into a 2D array
    if (ndim > 2):
        raise ValueError("state-space matrix must be 2-dimensional")

    elif (ndim == 2 and shape == (1, 0)) or \
         (ndim == 1 and shape == (0, )):
        # Passed an empty matrix or empty vector; change shape to (0, 0)
        shape = (0, 0)

    elif ndim == 1:
        # Passed a row or column vector
        shape = (1, shape[0]) if axis == 1 else (shape[0], 1)

    elif ndim == 0:
        # Passed a constant; turn into a matrix
        shape = (1, 1)

    #  Create the actual object used to store the result
    return arr.reshape(shape)


def _f2s(f):
    """Format floating point number f for StateSpace._repr_latex_.

    Numbers are converted to strings with statesp.latex_num_format.

    Inserts column separators, etc., as needed.
    """
    fmt = "{:" + config.defaults['statesp.latex_num_format'] + "}"
    sraw = fmt.format(f)
    # significand-exponent
    se = sraw.lower().split('e')
    # whole-fraction
    wf = se[0].split('.')
    s = wf[0]
    if wf[1:]:
        s += r'.&\hspace{{-1em}}{frac}'.format(frac=wf[1])
    else:
        s += r'\phantom{.}&\hspace{-1em}'

    if se[1:]:
        s += r'&\hspace{{-1em}}\cdot10^{{{:d}}}'.format(int(se[1]))
    else:
        s += r'&\hspace{-1em}\phantom{\cdot}'

    return s


class StateSpace(LTI):
    """StateSpace(A, B, C, D[, dt])

    A class for representing state-space models

    The StateSpace class is used to represent state-space realizations of
    linear time-invariant (LTI) systems:

        dx/dt = A x + B u
            y = C x + D u

    where u is the input, y is the output, and x is the state.

    The main data members are the A, B, C, and D matrices.  The class also
    keeps track of the number of states (i.e., the size of A).  The data
    format used to store state space matrices is set using the value of
    `config.defaults['use_numpy_matrix']`.  If True (default), the state space
    elements are stored as `numpy.matrix` objects; otherwise they are
    `numpy.ndarray` objects.  The :func:`~control.use_numpy_matrix` function
    can be used to set the storage type.

    A discrete time system is created by specifying a nonzero 'timebase', dt
    when the system is constructed:

    * dt = 0: continuous time system (default)
    * dt > 0: discrete time system with sampling period 'dt'
    * dt = True: discrete time with unspecified sampling period
    * dt = None: no timebase specified

    Systems must have compatible timebases in order to be combined. A discrete
    time system with unspecified sampling time (`dt = True`) can be combined
    with a system having a specified sampling time; the result will be a
    discrete time system with the sample time of the latter system. Similarly,
    a system with timebase `None` can be combined with a system having any
    timebase; the result will have the timebase of the latter system.
    The default value of dt can be changed by changing the value of
    ``control.config.defaults['control.default_dt']``.

    StateSpace instances have support for IPython LaTeX output,
    intended for pretty-printing in Jupyter notebooks.  The LaTeX
    output can be configured using
    `control.config.defaults['statesp.latex_num_format']` and
    `control.config.defaults['statesp.latex_repr_type']`.  The LaTeX output is
    tailored for MathJax, as used in Jupyter, and may look odd when
    typeset by non-MathJax LaTeX systems.

    `control.config.defaults['statesp.latex_num_format']` is a format string
    fragment, specifically the part of the format string after `'{:'`
    used to convert floating-point numbers to strings.  By default it
    is `'.3g'`.

    `control.config.defaults['statesp.latex_repr_type']` must either be
    `'partitioned'` or `'separate'`.  If `'partitioned'`, the A, B, C, D
    matrices are shown as a single, partitioned matrix; if
    `'separate'`, the matrices are shown separately.
    """

    # Allow ndarray * StateSpace to give StateSpace._rmul_() priority
    __array_priority__ = 11     # override ndarray and matrix types

    def __init__(self, *args, **kwargs):
        """StateSpace(A, B, C, D[, dt])

        Construct a state space object.

        The default constructor is StateSpace(A, B, C, D), where A, B, C, D
        are matrices or equivalent objects.  To create a discrete time system,
        use StateSpace(A, B, C, D, dt) where `dt` is the sampling time (or
        True for unspecified sampling time).  To call the copy constructor,
        call StateSpace(sys), where sys is a StateSpace object.

        The `remove_useless_states` keyword can be used to scan the A, B, and
        C matrices for rows or columns of zeros.  If the zeros are such that a
        particular state has no effect on the input-output dynamics, then that
        state is removed from the A, B, and C matrices.  If not specified, the
        value is read from `config.defaults['statesp.remove_useless_states']`
        (default = False).

        """
        # first get A, B, C, D matrices
        if len(args) == 4:
            # The user provided A, B, C, and D matrices.
            (A, B, C, D) = args
        elif len(args) == 5:
            # Discrete time system
            (A, B, C, D, _) = args
        elif len(args) == 1:
            # Use the copy constructor.
            if not isinstance(args[0], StateSpace):
                raise TypeError(
                    "The one-argument constructor can only take in a "
                    "StateSpace object. Received %s." % type(args[0]))
            A = args[0].A
            B = args[0].B
            C = args[0].C
            D = args[0].D
        else:
            raise ValueError(
                "Expected 1, 4, or 5 arguments; received %i." % len(args))

        # Process keyword arguments
        remove_useless_states = kwargs.get(
            'remove_useless_states',
            config.defaults['statesp.remove_useless_states'])

        # Convert all matrices to standard form
        A = _ssmatrix(A)
        # if B is a 1D array, turn it into a column vector if it fits
        if np.asarray(B).ndim == 1 and len(B) == A.shape[0]:
            B = _ssmatrix(B, axis=0)
        else:
            B = _ssmatrix(B)
        if np.asarray(C).ndim == 1 and len(C) == A.shape[0]:
            C = _ssmatrix(C, axis=1)
        else:
            C = _ssmatrix(C, axis=0)    # if this doesn't work, error below
        if np.isscalar(D) and D == 0 and B.shape[1] > 0 and C.shape[0] > 0:
            # If D is a scalar zero, broadcast it to the proper size
            D = np.zeros((C.shape[0], B.shape[1]))
        D = _ssmatrix(D)

        # TODO: use super here?
        LTI.__init__(self, inputs=D.shape[1], outputs=D.shape[0])
        self.A = A
        self.B = B
        self.C = C
        self.D = D

        # now set dt
        if len(args) == 4:
            if 'dt' in kwargs:
                dt = kwargs['dt']
            elif self._isstatic():
                dt = None
            else:
                dt = config.defaults['control.default_dt']
        elif len(args) == 5:
            dt = args[4]
            if 'dt' in kwargs:
                warn('received multiple dt arguments, using positional arg dt=%s'%dt)
        elif len(args) == 1:
            try:
                dt = args[0].dt
            except AttributeError:
                if self._isstatic():
                    dt = None
                else:
                    dt = config.defaults['control.default_dt']
        self.dt = dt
        self.nstates = A.shape[1]

        if 0 == self.nstates:
            # static gain
            # matrix's default "empty" shape is 1x0
            A.shape = (0, 0)
            B.shape = (0, self.ninputs)
            C.shape = (self.noutputs, 0)

        # Check that the matrix sizes are consistent.
        if self.nstates != A.shape[0]:
            raise ValueError("A must be square.")
        if self.nstates != B.shape[0]:
            raise ValueError("A and B must have the same number of rows.")
        if self.nstates != C.shape[1]:
            raise ValueError("A and C must have the same number of columns.")
        if self.ninputs != B.shape[1]:
            raise ValueError("B and D must have the same number of columns.")
        if self.noutputs != C.shape[0]:
            raise ValueError("C and D must have the same number of rows.")

        # Check for states that don't do anything, and remove them.
        if remove_useless_states:
            self._remove_useless_states()

    #
    # Getter and setter functions for legacy state attributes
    #
    # For this iteration, generate a deprecation warning whenever the
    # getter/setter is called.  For a future iteration, turn it into a
    # future warning, so that users will see it.
    #

    @property
    def states(self):
        warn("The StateSpace `states` attribute will be deprecated in a "
             "future release.  Use `nstates` instead.",
             DeprecationWarning, stacklevel=2)
        return self.nstates

    @states.setter
    def states(self, value):
        warn("The StateSpace `states` attribute will be deprecated in a "
             "future release.  Use `nstates` instead.",
             DeprecationWarning, stacklevel=2)
        self.nstates = value

    def _remove_useless_states(self):
        """Check for states that don't do anything, and remove them.

        Scan the A, B, and C matrices for rows or columns of zeros.  If the
        zeros are such that a particular state has no effect on the input-
        output dynamics, then remove that state from the A, B, and C matrices.

        """

        # Search for useless states and get indices of these states.
        #
        # Note: shape from np.where depends on whether we are storing state
        # space objects as np.matrix or np.array.  Code below will work
        # correctly in either case.
        ax1_A = np.where(~self.A.any(axis=1))[0]
        ax1_B = np.where(~self.B.any(axis=1))[0]
        ax0_A = np.where(~self.A.any(axis=0))[-1]
        ax0_C = np.where(~self.C.any(axis=0))[-1]
        useless_1 = np.intersect1d(ax1_A, ax1_B, assume_unique=True)
        useless_2 = np.intersect1d(ax0_A, ax0_C, assume_unique=True)
        useless = np.union1d(useless_1, useless_2)

        # Remove the useless states.
        self.A = delete(self.A, useless, 0)
        self.A = delete(self.A, useless, 1)
        self.B = delete(self.B, useless, 0)
        self.C = delete(self.C, useless, 1)

        self.nstates = self.A.shape[0]
        self.ninputs = self.B.shape[1]
        self.noutputs = self.C.shape[0]

    def __str__(self):
        """Return string representation of the state space system."""
        string = "\n".join([
            "{} = {}\n".format(Mvar,
                               "\n    ".join(str(M).splitlines()))
            for Mvar, M in zip(["A", "B", "C", "D"],
                               [self.A, self.B, self.C, self.D])])
        # TODO: replace with standard calls to lti functions
        if (type(self.dt) == bool and self.dt is True):
            string += "\ndt unspecified\n"
        elif (not (self.dt is None) and type(self.dt) != bool and self.dt > 0):
            string += "\ndt = " + self.dt.__str__() + "\n"
        return string

    # represent to implement a re-loadable version
    # TODO: remove the conversion to array when matrix is no longer used
    def __repr__(self):
        """Print state-space system in loadable form."""
        return "StateSpace({A}, {B}, {C}, {D}{dt})".format(
            A=asarray(self.A).__repr__(), B=asarray(self.B).__repr__(),
            C=asarray(self.C).__repr__(), D=asarray(self.D).__repr__(),
            dt=(isdtime(self, strict=True) and ", {}".format(self.dt)) or '')

    def _latex_partitioned_stateless(self):
        """`Partitioned` matrix LaTeX representation for stateless systems

        Model is presented as a matrix, D.  No partition lines are shown.

        Returns
        -------
        s : string with LaTeX representation of model
        """
        lines = [
            r'\[',
            r'\left(',
            (r'\begin{array}'
             + r'{' + 'rll' * self.ninputs + '}')
            ]

        for Di in asarray(self.D):
            lines.append('&'.join(_f2s(Dij) for Dij in Di)
                         + '\\\\')

        lines.extend([
            r'\end{array}'
            r'\right)',
            r'\]'])

        return '\n'.join(lines)

    def _latex_partitioned(self):
        """Partitioned matrix LaTeX representation of state-space model

        Model is presented as a matrix partitioned into A, B, C, and D
        parts.

        Returns
        -------
        s : string with LaTeX representation of model
        """
        if self.nstates == 0:
            return self._latex_partitioned_stateless()

        lines = [
            r'\[',
            r'\left(',
            (r'\begin{array}'
             + r'{' + 'rll' * self.nstates + '|' + 'rll' * self.ninputs + '}')
            ]

        for Ai, Bi in zip(asarray(self.A), asarray(self.B)):
            lines.append('&'.join([_f2s(Aij) for Aij in Ai]
                                  + [_f2s(Bij) for Bij in Bi])
                         + '\\\\')
        lines.append(r'\hline')
        for Ci, Di in zip(asarray(self.C), asarray(self.D)):
            lines.append('&'.join([_f2s(Cij) for Cij in Ci]
                                  + [_f2s(Dij) for Dij in Di])
                         + '\\\\')

        lines.extend([
            r'\end{array}'
            r'\right)',
            r'\]'])

        return '\n'.join(lines)

    def _latex_separate(self):
        """Separate matrices LaTeX representation of state-space model

        Model is presented as separate, named, A, B, C, and D matrices.

        Returns
        -------
        s : string with LaTeX representation of model
        """
        lines = [
            r'\[',
            r'\begin{array}{ll}',
            ]

        def fmt_matrix(matrix, name):
            matlines = [name
                        + r' = \left(\begin{array}{'
                        + 'rll' * matrix.shape[1]
                        + '}']
            for row in asarray(matrix):
                matlines.append('&'.join(_f2s(entry) for entry in row)
                                + '\\\\')
            matlines.extend([
                r'\end{array}'
                r'\right)'])
            return matlines

        if self.nstates > 0:
            lines.extend(fmt_matrix(self.A, 'A'))
            lines.append('&')
            lines.extend(fmt_matrix(self.B, 'B'))
            lines.append('\\\\')

            lines.extend(fmt_matrix(self.C, 'C'))
            lines.append('&')
        lines.extend(fmt_matrix(self.D, 'D'))

        lines.extend([
            r'\end{array}',
            r'\]'])

        return '\n'.join(lines)

    def _repr_latex_(self):
        """LaTeX representation of state-space model

        Output is controlled by config options statesp.latex_repr_type
        and statesp.latex_num_format.

        The output is primarily intended for Jupyter notebooks, which
        use MathJax to render the LaTeX, and the results may look odd
        when processed by a 'conventional' LaTeX system.

        Returns
        -------
        s : string with LaTeX representation of model

        """
        if config.defaults['statesp.latex_repr_type'] == 'partitioned':
            return self._latex_partitioned()
        elif config.defaults['statesp.latex_repr_type'] == 'separate':
            return self._latex_separate()
        else:
            cfg = config.defaults['statesp.latex_repr_type']
            raise ValueError(
                "Unknown statesp.latex_repr_type '{cfg}'".format(cfg=cfg))

    # Negation of a system
    def __neg__(self):
        """Negate a state space system."""

        return StateSpace(self.A, self.B, -self.C, -self.D, self.dt)

    # Addition of two state space systems (parallel interconnection)
    def __add__(self, other):
        """Add two LTI systems (parallel connection)."""

        # Check for a couple of special cases
        if isinstance(other, (int, float, complex, np.number)):
            # Just adding a scalar; put it in the D matrix
            A, B, C = self.A, self.B, self.C
            D = self.D + other
            dt = self.dt
        else:
            other = _convert_to_statespace(other)

            # Check to make sure the dimensions are OK
            if ((self.ninputs != other.ninputs) or
                    (self.noutputs != other.noutputs)):
                raise ValueError("Systems have different shapes.")

            dt = common_timebase(self.dt, other.dt)

            # Concatenate the various arrays
            A = concatenate((
                concatenate((self.A, zeros((self.A.shape[0],
                                            other.A.shape[-1]))), axis=1),
                concatenate((zeros((other.A.shape[0], self.A.shape[-1])),
                             other.A), axis=1)), axis=0)
            B = concatenate((self.B, other.B), axis=0)
            C = concatenate((self.C, other.C), axis=1)
            D = self.D + other.D

        return StateSpace(A, B, C, D, dt)

    # Right addition - just switch the arguments
    def __radd__(self, other):
        """Right add two LTI systems (parallel connection)."""

        return self + other

    # Subtraction of two state space systems (parallel interconnection)
    def __sub__(self, other):
        """Subtract two LTI systems."""

        return self + (-other)

    def __rsub__(self, other):
        """Right subtract two LTI systems."""

        return other + (-self)

    # Multiplication of two state space systems (series interconnection)
    def __mul__(self, other):
        """Multiply two LTI objects (serial connection)."""

        # Check for a couple of special cases
        if isinstance(other, (int, float, complex, np.number)):
            # Just multiplying by a scalar; change the output
            A, B = self.A, self.B
            C = self.C * other
            D = self.D * other
            dt = self.dt
        else:
            other = _convert_to_statespace(other)

            # Check to make sure the dimensions are OK
            if self.ninputs != other.noutputs:
                raise ValueError("C = A * B: A has %i column(s) (input(s)), \
                    but B has %i row(s)\n(output(s))." % (self.ninputs, other.noutputs))
            dt = common_timebase(self.dt, other.dt)

            # Concatenate the various arrays
            A = concatenate(
                (concatenate((other.A,
                              zeros((other.A.shape[0], self.A.shape[1]))),
                             axis=1),
                 concatenate((np.dot(self.B, other.C), self.A), axis=1)),
                axis=0)
            B = concatenate((other.B, np.dot(self.B, other.D)), axis=0)
            C = concatenate((np.dot(self.D, other.C), self.C), axis=1)
            D = np.dot(self.D, other.D)

        return StateSpace(A, B, C, D, dt)

    # Right multiplication of two state space systems (series interconnection)
    # Just need to convert LH argument to a state space object
    # TODO: __rmul__ only works for special cases (??)
    def __rmul__(self, other):
        """Right multiply two LTI objects (serial connection)."""

        # Check for a couple of special cases
        if isinstance(other, (int, float, complex, np.number)):
            # Just multiplying by a scalar; change the input
            A, C = self.A, self.C
            B = self.B * other
            D = self.D * other
            return StateSpace(A, B, C, D, self.dt)

        # is lti, and convertible?
        if isinstance(other, LTI):
            return _convert_to_statespace(other) * self

        # try to treat this as a matrix
        try:
            X = _ssmatrix(other)
            C = np.dot(X, self.C)
            D = np.dot(X, self.D)
            return StateSpace(self.A, self.B, C, D, self.dt)

        except Exception as e:
            print(e)
            pass
        raise TypeError("can't interconnect systems")

    # TODO: __div__ and __rdiv__ are not written yet.
    def __div__(self, other):
        """Divide two LTI systems."""

        raise NotImplementedError("StateSpace.__div__ is not implemented yet.")

    def __rdiv__(self, other):
        """Right divide two LTI systems."""

        raise NotImplementedError(
            "StateSpace.__rdiv__ is not implemented yet.")

    def __call__(self, x, squeeze=None, warn_infinite=True):
        """Evaluate system's transfer function at complex frequency.

        Returns the complex frequency response `sys(x)` where `x` is `s` for
        continuous-time systems and `z` for discrete-time systems.

        To evaluate at a frequency omega in radians per second, enter
        ``x = omega * 1j``, for continuous-time systems, or
        ``x = exp(1j * omega * dt)`` for discrete-time systems. Or use
        :meth:`StateSpace.frequency_response`.

        Parameters
        ----------
        x : complex or complex 1D array_like
            Complex frequencies
        squeeze : bool, optional
            If squeeze=True, remove single-dimensional entries from the shape
            of the output even if the system is not SISO. If squeeze=False,
            keep all indices (output, input and, if omega is array_like,
            frequency) even if the system is SISO. The default value can be
            set using config.defaults['control.squeeze_frequency_response'].
        warn_infinite : bool, optional
            If set to `False`, don't warn if frequency response is infinite.

        Returns
        -------
        fresp : complex ndarray
            The frequency response of the system.  If the system is SISO and
            squeeze is not True, the shape of the array matches the shape of
            omega.  If the system is not SISO or squeeze is False, the first
            two dimensions of the array are indices for the output and input
            and the remaining dimensions match omega.  If ``squeeze`` is True
            then single-dimensional axes are removed.

        """
        # Use Slycot if available
        out = self.horner(x, warn_infinite=warn_infinite)
        return _process_frequency_response(self, x, out, squeeze=squeeze)

    def slycot_laub(self, x):
        """Evaluate system's transfer function at complex frequency
        using Laub's method from Slycot.

        Expects inputs and outputs to be formatted correctly. Use ``sys(x)``
        for a more user-friendly interface.

        Parameters
        ----------
        x : complex array_like or complex
            Complex frequency

        Returns
        -------
        output : (number_outputs, number_inputs, len(x)) complex ndarray
            Frequency response
        """
        from slycot import tb05ad

        # Make sure the argument is a 1D array of complex numbers
        x_arr = np.atleast_1d(x).astype(complex, copy=False)

        # Make sure that we are operating on a simple list
        if len(x_arr.shape) > 1:
            raise ValueError("input list must be 1D")

        # preallocate
        n = self.nstates
        m = self.ninputs
        p = self.noutputs
        out = np.empty((p, m, len(x_arr)), dtype=complex)
        # The first call both evaluates C(sI-A)^-1 B and also returns
        # Hessenberg transformed matrices at, bt, ct.
        result = tb05ad(n, m, p, x_arr[0], self.A, self.B, self.C, job='NG')
        # When job='NG', result = (at, bt, ct, g_i, hinvb, info)
        at = result[0]
        bt = result[1]
        ct = result[2]

        # TB05AD frequency evaluation does not include direct feedthrough.
        out[:, :, 0] = result[3] + self.D

        # Now, iterate through the remaining frequencies using the
        # transformed state matrices, at, bt, ct.

        # Start at the second frequency, already have the first.
        for kk, x_kk in enumerate(x_arr[1:len(x_arr)]):
            result = tb05ad(n, m, p, x_kk, at, bt, ct, job='NH')
            # When job='NH', result = (g_i, hinvb, info)

            # kk+1 because enumerate starts at kk = 0.
            # but zero-th spot is already filled.
            out[:, :, kk+1] = result[0] + self.D
        return out

    def horner(self, x, warn_infinite=True):
        """Evaluate system's transfer function at complex frequency
        using Laub's or Horner's method.

        Evaluates `sys(x)` where `x` is `s` for continuous-time systems and `z`
        for discrete-time systems.

        Expects inputs and outputs to be formatted correctly. Use ``sys(x)``
        for a more user-friendly interface.

        Parameters
        ----------
        x : complex array_like or complex
            Complex frequencies

        Returns
        -------
        output : (self.noutputs, self.ninputs, len(x)) complex ndarray
            Frequency response

        Notes
        -----
        Attempts to use Laub's method from Slycot library, with a
        fall-back to python code.
        """
        try:
            out = self.slycot_laub(x)
        except (ImportError, Exception):
            # Fall back because either Slycot unavailable or cannot handle
            # certain cases.

            # Make sure the argument is a 1D array of complex numbers
            x_arr = np.atleast_1d(x).astype(complex, copy=False)

            # Make sure that we are operating on a simple list
            if len(x_arr.shape) > 1:
                raise ValueError("input list must be 1D")

            # Preallocate
            out = empty((self.noutputs, self.ninputs, len(x_arr)),
                        dtype=complex)

            #TODO: can this be vectorized?
            for idx, x_idx in enumerate(x_arr):
                try:
                    out[:,:,idx] = np.dot(
                        self.C,
                        solve(x_idx * eye(self.nstates) - self.A, self.B)) \
                        + self.D
                except LinAlgError:
                    # Issue a warning messsage, for consistency with xferfcn
                    if warn_infinite:
                        warn("singular matrix in frequency response",
                             RuntimeWarning)

                    # Evaluating at a pole.  Return value depends if there
                    # is a zero at the same point or not.
                    if x_idx in self.zero():
                        out[:,:,idx] = complex(np.nan, np.nan)
                    else:
                        out[:,:,idx] = complex(np.inf, np.nan)

        return out

    def freqresp(self, omega):
        """(deprecated) Evaluate transfer function at complex frequencies.

        .. deprecated::0.9.0
            Method has been given the more pythonic name
            :meth:`StateSpace.frequency_response`. Or use
            :func:`freqresp` in the MATLAB compatibility module.
        """
        warn("StateSpace.freqresp(omega) will be removed in a "
             "future release of python-control; use "
             "sys.frequency_response(omega), or freqresp(sys, omega) in the "
             "MATLAB compatibility module instead", DeprecationWarning)
        return self.frequency_response(omega)

    # Compute poles and zeros
    def pole(self):
        """Compute the poles of a state space system."""

        return eigvals(self.A) if self.nstates else np.array([])

    def zero(self):
        """Compute the zeros of a state space system."""

        if not self.nstates:
            return np.array([])

        # Use AB08ND from Slycot if it's available, otherwise use
        # scipy.lingalg.eigvals().
        try:
            from slycot import ab08nd

            out = ab08nd(self.A.shape[0], self.B.shape[1], self.C.shape[0],
                         self.A, self.B, self.C, self.D)
            nu = out[0]
            if nu == 0:
                return np.array([])
            else:
                return sp.linalg.eigvals(out[8][0:nu, 0:nu],
                                         out[9][0:nu, 0:nu])

        except ImportError:  # Slycot unavailable. Fall back to scipy.
            if self.C.shape[0] != self.D.shape[1]:
                raise NotImplementedError("StateSpace.zero only supports "
                                          "systems with the same number of "
                                          "inputs as outputs.")

            # This implements the QZ algorithm for finding transmission zeros
            # from
            # https://dspace.mit.edu/bitstream/handle/1721.1/841/P-0802-06587335.pdf.
            # The QZ algorithm solves the generalized eigenvalue problem: given
            # `L = [A, B; C, D]` and `M = [I_nxn 0]`, find all finite lambda
            # for which there exist nontrivial solutions of the equation
            # `Lz - lamba Mz`.
            #
            # The generalized eigenvalue problem is only solvable if its
            # arguments are square matrices.
            L = concatenate((concatenate((self.A, self.B), axis=1),
                             concatenate((self.C, self.D), axis=1)), axis=0)
            M = pad(eye(self.A.shape[0]), ((0, self.C.shape[0]),
                                           (0, self.B.shape[1])), "constant")
            return np.array([x for x in sp.linalg.eigvals(L, M,
                                                          overwrite_a=True)
                             if not isinf(x)])

    # Feedback around a state space system
    def feedback(self, other=1, sign=-1):
        """Feedback interconnection between two LTI systems."""

        other = _convert_to_statespace(other)

        # Check to make sure the dimensions are OK
        if (self.ninputs != other.noutputs) or (self.noutputs != other.ninputs):
            raise ValueError("State space systems don't have compatible "
                             "inputs/outputs for feedback.")
        dt = common_timebase(self.dt, other.dt)

        A1 = self.A
        B1 = self.B
        C1 = self.C
        D1 = self.D
        A2 = other.A
        B2 = other.B
        C2 = other.C
        D2 = other.D

        F = eye(self.ninputs) - sign * np.dot(D2, D1)
        if matrix_rank(F) != self.ninputs:
            raise ValueError(
                "I - sign * D2 * D1 is singular to working precision.")

        # Precompute F\D2 and F\C2 (E = inv(F))
        # We can solve two linear systems in one pass, since the
        # coefficients matrix F is the same. Thus, we perform the LU
        # decomposition (cubic runtime complexity) of F only once!
        # The remaining back substitutions are only quadratic in runtime.
        E_D2_C2 = solve(F, concatenate((D2, C2), axis=1))
        E_D2 = E_D2_C2[:, :other.ninputs]
        E_C2 = E_D2_C2[:, other.ninputs:]

        T1 = eye(self.noutputs) + sign * np.dot(D1, E_D2)
        T2 = eye(self.ninputs) + sign * np.dot(E_D2, D1)

        A = concatenate(
            (concatenate(
                (A1 + sign * np.dot(np.dot(B1, E_D2), C1),
                 sign * np.dot(B1, E_C2)), axis=1),
             concatenate(
                 (np.dot(B2, np.dot(T1, C1)),
                  A2 + sign * np.dot(np.dot(B2, D1), E_C2)), axis=1)),
            axis=0)
        B = concatenate((np.dot(B1, T2), np.dot(np.dot(B2, D1), T2)), axis=0)
        C = concatenate((np.dot(T1, C1), sign * np.dot(D1, E_C2)), axis=1)
        D = np.dot(D1, T2)

        return StateSpace(A, B, C, D, dt)

    def lft(self, other, nu=-1, ny=-1):
        """Return the Linear Fractional Transformation.

        A definition of the LFT operator can be found in Appendix A.7,
        page 512 in the 2nd Edition, Multivariable Feedback Control by
        Sigurd Skogestad.

        An alternative definition can be found here:
        https://www.mathworks.com/help/control/ref/lft.html

        Parameters
        ----------
        other : LTI
            The lower LTI system
        ny : int, optional
            Dimension of (plant) measurement output.
        nu : int, optional
            Dimension of (plant) control input.

        """
        other = _convert_to_statespace(other)
        # maximal values for nu, ny
        if ny == -1:
            ny = min(other.ninputs, self.noutputs)
        if nu == -1:
            nu = min(other.noutputs, self.ninputs)
        # dimension check
        # TODO

        dt = common_timebase(self.dt, other.dt)

        # submatrices
        A = self.A
        B1 = self.B[:, :self.ninputs - nu]
        B2 = self.B[:, self.ninputs - nu:]
        C1 = self.C[:self.noutputs - ny, :]
        C2 = self.C[self.noutputs - ny:, :]
        D11 = self.D[:self.noutputs - ny, :self.ninputs - nu]
        D12 = self.D[:self.noutputs - ny, self.ninputs - nu:]
        D21 = self.D[self.noutputs - ny:, :self.ninputs - nu]
        D22 = self.D[self.noutputs - ny:, self.ninputs - nu:]

        # submatrices
        Abar = other.A
        Bbar1 = other.B[:, :ny]
        Bbar2 = other.B[:, ny:]
        Cbar1 = other.C[:nu, :]
        Cbar2 = other.C[nu:, :]
        Dbar11 = other.D[:nu, :ny]
        Dbar12 = other.D[:nu, ny:]
        Dbar21 = other.D[nu:, :ny]
        Dbar22 = other.D[nu:, ny:]

        # well-posed check
        F = np.block([[np.eye(ny), -D22], [-Dbar11, np.eye(nu)]])
        if matrix_rank(F) != ny + nu:
            raise ValueError("lft not well-posed to working precision.")

        # solve for the resulting ss by solving for [y, u] using [x,
        # xbar] and [w1, w2].
        TH = np.linalg.solve(F, np.block(
            [[C2, np.zeros((ny, other.nstates)),
              D21, np.zeros((ny, other.ninputs - ny))],
             [np.zeros((nu, self.nstates)), Cbar1,
              np.zeros((nu, self.ninputs - nu)), Dbar12]]
        ))
        T11 = TH[:ny, :self.nstates]
        T12 = TH[:ny, self.nstates: self.nstates + other.nstates]
        T21 = TH[ny:, :self.nstates]
        T22 = TH[ny:, self.nstates: self.nstates + other.nstates]
        H11 = TH[:ny, self.nstates + other.nstates:self.nstates +
                 other.nstates + self.ninputs - nu]
        H12 = TH[:ny, self.nstates + other.nstates + self.ninputs - nu:]
        H21 = TH[ny:, self.nstates + other.nstates:self.nstates +
                 other.nstates + self.ninputs - nu]
        H22 = TH[ny:, self.nstates + other.nstates + self.ninputs - nu:]

        Ares = np.block([
            [A + B2.dot(T21), B2.dot(T22)],
            [Bbar1.dot(T11), Abar + Bbar1.dot(T12)]
        ])

        Bres = np.block([
            [B1 + B2.dot(H21), B2.dot(H22)],
            [Bbar1.dot(H11), Bbar2 + Bbar1.dot(H12)]
        ])

        Cres = np.block([
            [C1 + D12.dot(T21), D12.dot(T22)],
            [Dbar21.dot(T11), Cbar2 + Dbar21.dot(T12)]
        ])

        Dres = np.block([
            [D11 + D12.dot(H21), D12.dot(H22)],
            [Dbar21.dot(H11), Dbar22 + Dbar21.dot(H12)]
        ])
        return StateSpace(Ares, Bres, Cres, Dres, dt)

    def minreal(self, tol=0.0):
        """Calculate a minimal realization, removes unobservable and
        uncontrollable states"""
        if self.nstates:
            try:
                from slycot import tb01pd
                B = empty((self.nstates, max(self.ninputs, self.noutputs)))
                B[:, :self.ninputs] = self.B
                C = empty((max(self.noutputs, self.ninputs), self.nstates))
                C[:self.noutputs, :] = self.C
                A, B, C, nr = tb01pd(self.nstates, self.ninputs, self.noutputs,
                                     self.A, B, C, tol=tol)
                return StateSpace(A[:nr, :nr], B[:nr, :self.ninputs],
                                  C[:self.noutputs, :nr], self.D)
            except ImportError:
                raise TypeError("minreal requires slycot tb01pd")
        else:
            return StateSpace(self)

    def returnScipySignalLTI(self, strict=True):
        """Return a list of a list of :class:`scipy.signal.lti` objects.

        For instance,

        >>> out = ssobject.returnScipySignalLTI()
        >>> out[3][5]

        is a :class:`scipy.signal.lti` object corresponding to the transfer
        function from the 6th input to the 4th output.

        Parameters
        ----------
        strict : bool, optional
            True (default):
                The timebase `ssobject.dt` cannot be None; it must
                be continuous (0) or discrete (True or > 0).
            False:
              If `ssobject.dt` is None, continuous time
              :class:`scipy.signal.lti` objects are returned.

        Returns
        -------
        out : list of list of :class:`scipy.signal.StateSpace`
            continuous time (inheriting from :class:`scipy.signal.lti`)
            or discrete time (inheriting from :class:`scipy.signal.dlti`)
            SISO objects
        """
        if strict and self.dt is None:
            raise ValueError("with strict=True, dt cannot be None")

        if self.dt:
            kwdt = {'dt': self.dt}
        else:
            # scipy convention for continuous time lti systems: call without
            # dt keyword argument
            kwdt = {}

        # Preallocate the output.
        out = [[[] for _ in range(self.ninputs)] for _ in range(self.noutputs)]

        for i in range(self.noutputs):
            for j in range(self.ninputs):
                out[i][j] = signalStateSpace(asarray(self.A),
                                             asarray(self.B[:, j:j + 1]),
                                             asarray(self.C[i:i + 1, :]),
                                             asarray(self.D[i:i + 1, j:j + 1]),
                                             **kwdt)

        return out

    def append(self, other):
        """Append a second model to the present model.

        The second model is converted to state-space if necessary, inputs and
        outputs are appended and their order is preserved"""
        if not isinstance(other, StateSpace):
            other = _convert_to_statespace(other)

        self.dt = common_timebase(self.dt, other.dt)

        n = self.nstates + other.nstates
        m = self.ninputs + other.ninputs
        p = self.noutputs + other.noutputs
        A = zeros((n, n))
        B = zeros((n, m))
        C = zeros((p, n))
        D = zeros((p, m))
        A[:self.nstates, :self.nstates] = self.A
        A[self.nstates:, self.nstates:] = other.A
        B[:self.nstates, :self.ninputs] = self.B
        B[self.nstates:, self.ninputs:] = other.B
        C[:self.noutputs, :self.nstates] = self.C
        C[self.noutputs:, self.nstates:] = other.C
        D[:self.noutputs, :self.ninputs] = self.D
        D[self.noutputs:, self.ninputs:] = other.D
        return StateSpace(A, B, C, D, self.dt)

    def __getitem__(self, indices):
        """Array style access"""
        if len(indices) != 2:
            raise IOError('must provide indices of length 2 for state space')
        i = indices[0]
        j = indices[1]
        return StateSpace(self.A, self.B[:, j], self.C[i, :],
                          self.D[i, j], self.dt)

    def sample(self, Ts, method='zoh', alpha=None, prewarp_frequency=None):
        """Convert a continuous time system to discrete time

        Creates a discrete-time system from a continuous-time system by
        sampling.  Multiple methods of conversion are supported.

        Parameters
        ----------
        Ts : float
            Sampling period
        method :  {"gbt", "bilinear", "euler", "backward_diff", "zoh"}
            Which method to use:

            * gbt: generalized bilinear transformation
            * bilinear: Tustin's approximation ("gbt" with alpha=0.5)
            * euler: Euler (or forward differencing) method ("gbt" with
              alpha=0)
            * backward_diff: Backwards differencing ("gbt" with alpha=1.0)
            * zoh: zero-order hold (default)

        alpha : float within [0, 1]
            The generalized bilinear transformation weighting parameter, which
            should only be specified with method="gbt", and is ignored
            otherwise

        prewarp_frequency : float within [0, infinity)
            The frequency [rad/s] at which to match with the input continuous-
            time system's magnitude and phase (the gain=1 crossover frequency,
            for example). Should only be specified with method='bilinear' or
            'gbt' with alpha=0.5 and ignored otherwise.

        Returns
        -------
        sysd : StateSpace
            Discrete time system, with sampling rate Ts

        Notes
        -----
        Uses :func:`scipy.signal.cont2discrete`

        Examples
        --------
        >>> sys = StateSpace(0, 1, 1, 0)
        >>> sysd = sys.sample(0.5, method='bilinear')

        """
        if not self.isctime():
            raise ValueError("System must be continuous time system")

        sys = (self.A, self.B, self.C, self.D)
        if (method == 'bilinear' or (method == 'gbt' and alpha == 0.5)) and \
                prewarp_frequency is not None:
            Twarp = 2 * np.tan(prewarp_frequency * Ts/2)/prewarp_frequency
        else:
            Twarp = Ts
        Ad, Bd, C, D, _ = cont2discrete(sys, Twarp, method, alpha)
        return StateSpace(Ad, Bd, C, D, Ts)

    def dcgain(self, warn_infinite=False):
        """Return the zero-frequency gain

        The zero-frequency gain of a continuous-time state-space
        system is given by:

        .. math: G(0) = - C A^{-1} B + D

        and of a discrete-time state-space system by:

        .. math: G(1) = C (I - A)^{-1} B + D

        Parameters
        ----------
        warn_infinite : bool, optional
            By default, don't issue a warning message if the zero-frequency
            gain is infinite.  Setting `warn_infinite` to generate the warning
            message.

        Returns
        -------
        gain : (noutputs, ninputs) ndarray or scalar
            Array or scalar value for SISO systems, depending on
            config.defaults['control.squeeze_frequency_response'].
            The value of the array elements or the scalar is either the
            zero-frequency (or DC) gain, or `inf`, if the frequency response
            is singular.

            For real valued systems, the empty imaginary part of the
            complex zero-frequency response is discarded and a real array or
            scalar is returned.
        """
        return self._dcgain(warn_infinite)

    def dynamics(self, t, x, u=None):
        """Compute the dynamics of the system

        Given input `u` and state `x`, returns the dynamics of the state-space
        system. If the system is continuous, returns the time derivative dx/dt

            dx/dt = A x + B u

        where A and B are the state-space matrices of the system. If the
        system is discrete-time, returns the next value of `x`:

            x[t+dt] = A x[t] + B u[t]

        The inputs `x` and `u` must be of the correct length for the system.

        The first argument `t` is ignored because :class:`StateSpace` systems
        are time-invariant. It is included so that the dynamics can be passed
        to most numerical integrators, such as :func:`scipy.integrate.solve_ivp`
        and for consistency with :class:`IOSystem` systems.

        Parameters
        ----------
        t : float (ignored)
            time
        x : array_like
            current state
        u : array_like (optional)
            input, zero if omitted

        Returns
        -------
        dx/dt or x[t+dt] : ndarray
        """
        x = np.reshape(x, (-1, 1)) # force to a column in case matrix
        if np.size(x) != self.nstates:
            raise ValueError("len(x) must be equal to number of states")
        if u is None:
            return self.A.dot(x).reshape((-1,)) # return as row vector
        else: # received t, x, and u, ignore t
            u = np.reshape(u, (-1, 1)) # force to a column in case matrix
            if np.size(u) != self.ninputs:
                raise ValueError("len(u) must be equal to number of inputs")
            return self.A.dot(x).reshape((-1,)) \
                 + self.B.dot(u).reshape((-1,)) # return as row vector

    def output(self, t, x, u=None):
        """Compute the output of the system

        Given input `u` and state `x`, returns the output `y` of the
        state-space system:

            y = C x + D u

        where A and B are the state-space matrices of the system.

        The first argument `t` is ignored because :class:`StateSpace` systems
        are time-invariant. It is included so that the dynamics can be passed
        to most numerical integrators, such as scipy's `integrate.solve_ivp` and
        for consistency with :class:`IOSystem` systems.

        The inputs `x` and `u` must be of the correct length for the system.

        Parameters
        ----------
        t : float (ignored)
            time
        x : array_like
            current state
        u : array_like (optional)
            input (zero if omitted)

        Returns
        -------
        y : ndarray
        """
        x = np.reshape(x, (-1, 1)) # force to a column in case matrix
        if np.size(x) != self.nstates:
            raise ValueError("len(x) must be equal to number of states")

        if u is None:
            return self.C.dot(x).reshape((-1,)) # return as row vector
        else: # received t, x, and u, ignore t
            u = np.reshape(u, (-1, 1)) # force to a column in case matrix
            if np.size(u) != self.ninputs:
                raise ValueError("len(u) must be equal to number of inputs")
            return self.C.dot(x).reshape((-1,)) \
                 + self.D.dot(u).reshape((-1,)) # return as row vector

    def _isstatic(self):
        """True if and only if the system has no dynamics, that is,
        if A and B are zero. """
        return not np.any(self.A) and not np.any(self.B)



# TODO: add discrete time check
def _convert_to_statespace(sys, **kw):
    """Convert a system to state space form (if needed).

    If sys is already a state space, then it is returned.  If sys is a
    transfer function object, then it is converted to a state space and
    returned.  If sys is a scalar, then the number of inputs and outputs can
    be specified manually, as in:

    >>> sys = _convert_to_statespace(3.) # Assumes inputs = outputs = 1
    >>> sys = _convert_to_statespace(1., inputs=3, outputs=2)

    In the latter example, A = B = C = 0 and D = [[1., 1., 1.]
                                                  [1., 1., 1.]].
    """
    from .xferfcn import TransferFunction
    import itertools

    if isinstance(sys, StateSpace):
        if len(kw):
            raise TypeError("If sys is a StateSpace, _convert_to_statespace "
                            "cannot take keywords.")

        # Already a state space system; just return it
        return sys

    elif isinstance(sys, TransferFunction):
        # Make sure the transfer function is proper
        if any([[len(num) for num in col] for col in sys.num] >
               [[len(num) for num in col] for col in sys.den]):
            raise ValueError("Transfer function is non-proper; can't "
                             "convert to StateSpace system.")
        try:
            from slycot import td04ad
            if len(kw):
                raise TypeError("If sys is a TransferFunction, "
                                "_convert_to_statespace cannot take keywords.")

            # Change the numerator and denominator arrays so that the transfer
            # function matrix has a common denominator.
            # matrices are also sized/padded to fit td04ad
            num, den, denorder = sys.minreal()._common_den()

            # transfer function to state space conversion now should work!
            ssout = td04ad('C', sys.ninputs, sys.noutputs,
                           denorder, den, num, tol=0)

            states = ssout[0]
            return StateSpace(ssout[1][:states, :states],
                              ssout[2][:states, :sys.ninputs],
                              ssout[3][:sys.noutputs, :states], ssout[4],
                              sys.dt)
        except ImportError:
            # No Slycot.  Scipy tf->ss can't handle MIMO, but static
            # MIMO is an easy special case we can check for here
            maxn = max(max(len(n) for n in nrow)
                       for nrow in sys.num)
            maxd = max(max(len(d) for d in drow)
                       for drow in sys.den)
            if 1 == maxn and 1 == maxd:
                D = empty((sys.noutputs, sys.ninputs), dtype=float)
                for i, j in itertools.product(range(sys.noutputs),
                                              range(sys.ninputs)):
                    D[i, j] = sys.num[i][j][0] / sys.den[i][j][0]
                return StateSpace([], [], [], D, sys.dt)
            else:
                if sys.ninputs != 1 or sys.noutputs != 1:
                    raise TypeError("No support for MIMO without slycot")

                # TODO: do we want to squeeze first and check dimenations?
                # I think this will fail if num and den aren't 1-D after
                # the squeeze
                A, B, C, D = \
                    sp.signal.tf2ss(squeeze(sys.num), squeeze(sys.den))
                return StateSpace(A, B, C, D, sys.dt)

    elif isinstance(sys, (int, float, complex, np.number)):
        if "inputs" in kw:
            inputs = kw["inputs"]
        else:
            inputs = 1
        if "outputs" in kw:
            outputs = kw["outputs"]
        else:
            outputs = 1

        # Generate a simple state space system of the desired dimension
        # The following Doesn't work due to inconsistencies in ltisys:
        #   return StateSpace([[]], [[]], [[]], eye(outputs, inputs))
        return StateSpace([], zeros((0, inputs)), zeros((outputs, 0)),
                          sys * ones((outputs, inputs)))

    # If this is a matrix, try to create a constant feedthrough
    try:
        D = _ssmatrix(sys)
        return StateSpace([], [], [], D)
    except:
        raise TypeError("Can't convert given type to StateSpace system.")


# TODO: add discrete time option
def _rss_generate(states, inputs, outputs, type, strictly_proper=False):
    """Generate a random state space.

    This does the actual random state space generation expected from rss and
    drss.  type is 'c' for continuous systems and 'd' for discrete systems.

    """

    # Probability of repeating a previous root.
    pRepeat = 0.05
    # Probability of choosing a real root.  Note that when choosing a complex
    # root, the conjugate gets chosen as well.  So the expected proportion of
    # real roots is pReal / (pReal + 2 * (1 - pReal)).
    pReal = 0.6
    # Probability that an element in B or C will not be masked out.
    pBCmask = 0.8
    # Probability that an element in D will not be masked out.
    pDmask = 0.3
    # Probability that D = 0.
    pDzero = 0.5

    # Check for valid input arguments.
    if states < 1 or states % 1:
        raise ValueError("states must be a positive integer.  states = %g." %
                         states)
    if inputs < 1 or inputs % 1:
        raise ValueError("inputs must be a positive integer.  inputs = %g." %
                         inputs)
    if outputs < 1 or outputs % 1:
        raise ValueError("outputs must be a positive integer.  outputs = %g." %
                         outputs)

    # Make some poles for A.  Preallocate a complex array.
    poles = zeros(states) + zeros(states) * 0.j
    i = 0

    while i < states:
        if rand() < pRepeat and i != 0 and i != states - 1:
            # Small chance of copying poles, if we're not at the first or last
            # element.
            if poles[i-1].imag == 0:
                # Copy previous real pole.
                poles[i] = poles[i-1]
                i += 1
            else:
                # Copy previous complex conjugate pair of poles.
                poles[i:i+2] = poles[i-2:i]
                i += 2
        elif rand() < pReal or i == states - 1:
            # No-oscillation pole.
            if type == 'c':
                poles[i] = -exp(randn()) + 0.j
            elif type == 'd':
                poles[i] = 2. * rand() - 1.
            i += 1
        else:
            # Complex conjugate pair of oscillating poles.
            if type == 'c':
                poles[i] = complex(-exp(randn()), 3. * exp(randn()))
            elif type == 'd':
                mag = rand()
                phase = 2. * math.pi * rand()
                poles[i] = complex(mag * cos(phase), mag * sin(phase))
            poles[i+1] = complex(poles[i].real, -poles[i].imag)
            i += 2

    # Now put the poles in A as real blocks on the diagonal.
    A = zeros((states, states))
    i = 0
    while i < states:
        if poles[i].imag == 0:
            A[i, i] = poles[i].real
            i += 1
        else:
            A[i, i] = A[i+1, i+1] = poles[i].real
            A[i, i+1] = poles[i].imag
            A[i+1, i] = -poles[i].imag
            i += 2
    # Finally, apply a transformation so that A is not block-diagonal.
    while True:
        T = randn(states, states)
        try:
            A = dot(solve(T, A), T)  # A = T \ A * T
            break
        except LinAlgError:
            # In the unlikely event that T is rank-deficient, iterate again.
            pass

    # Make the remaining matrices.
    B = randn(states, inputs)
    C = randn(outputs, states)
    D = randn(outputs, inputs)

    # Make masks to zero out some of the elements.
    while True:
        Bmask = rand(states, inputs) < pBCmask
        if any(Bmask):  # Retry if we get all zeros.
            break
    while True:
        Cmask = rand(outputs, states) < pBCmask
        if any(Cmask):  # Retry if we get all zeros.
            break
    if rand() < pDzero:
        Dmask = zeros((outputs, inputs))
    else:
        Dmask = rand(outputs, inputs) < pDmask

    # Apply masks.
    B = B * Bmask
    C = C * Cmask
    D = D * Dmask if not strictly_proper else zeros(D.shape)

    return StateSpace(A, B, C, D)


# Convert a MIMO system to a SISO system
# TODO: add discrete time check
def _mimo2siso(sys, input, output, warn_conversion=False):
    # pylint: disable=W0622
    """
    Convert a MIMO system to a SISO system. (Convert a system with multiple
    inputs and/or outputs, to a system with a single input and output.)

    The input and output that are used in the SISO system can be selected
    with the parameters ``input`` and ``output``. All other inputs are set
    to 0, all other outputs are ignored.

    If ``sys`` is already a SISO system, it will be returned unaltered.

    Parameters
    ----------
    sys : StateSpace
        Linear (MIMO) system that should be converted.
    input : int
        Index of the input that will become the SISO system's only input.
    output : int
        Index of the output that will become the SISO system's only output.
    warn_conversion : bool, optional
        If `True`, print a message when sys is a MIMO system,
        warning that a conversion will take place.  Default is False.

    Returns
    sys : StateSpace
        The converted (SISO) system.
    """
    if not (isinstance(input, int) and isinstance(output, int)):
        raise TypeError("Parameters ``input`` and ``output`` must both "
                        "be integer numbers.")
    if not (0 <= input < sys.ninputs):
        raise ValueError("Selected input does not exist. "
                         "Selected input: {sel}, "
                         "number of system inputs: {ext}."
                         .format(sel=input, ext=sys.ninputs))
    if not (0 <= output < sys.noutputs):
        raise ValueError("Selected output does not exist. "
                         "Selected output: {sel}, "
                         "number of system outputs: {ext}."
                         .format(sel=output, ext=sys.noutputs))
    # Convert sys to SISO if necessary
    if sys.ninputs > 1 or sys.noutputs > 1:
        if warn_conversion:
            warn("Converting MIMO system to SISO system. "
                 "Only input {i} and output {o} are used."
                 .format(i=input, o=output))
        # $X = A*X + B*U
        #  Y = C*X + D*U
        new_B = sys.B[:, input]
        new_C = sys.C[output, :]
        new_D = sys.D[output, input]
        sys = StateSpace(sys.A, new_B, new_C, new_D, sys.dt)

    return sys


def _mimo2simo(sys, input, warn_conversion=False):
    # pylint: disable=W0622
    """
    Convert a MIMO system to a SIMO system. (Convert a system with multiple
    inputs and/or outputs, to a system with a single input but possibly
    multiple outputs.)

    The input that is used in the SIMO system can be selected with the
    parameter ``input``. All other inputs are set to 0, all other
    outputs are ignored.

    If ``sys`` is already a SIMO system, it will be returned unaltered.

    Parameters
    ----------
    sys: StateSpace
        Linear (MIMO) system that should be converted.
    input: int
        Index of the input that will become the SIMO system's only input.
    warn_conversion: bool
        If True: print a warning message when sys is a MIMO system.
        Warn that a conversion will take place.

    Returns
    -------
    sys: StateSpace
        The converted (SIMO) system.
    """
    if not (isinstance(input, int)):
        raise TypeError("Parameter ``input`` be an integer number.")
    if not (0 <= input < sys.ninputs):
        raise ValueError("Selected input does not exist. "
                         "Selected input: {sel}, "
                         "number of system inputs: {ext}."
                         .format(sel=input, ext=sys.ninputs))
    # Convert sys to SISO if necessary
    if sys.ninputs > 1:
        if warn_conversion:
            warn("Converting MIMO system to SIMO system. "
                 "Only input {i} is used." .format(i=input))
        # $X = A*X + B*U
        #  Y = C*X + D*U
        new_B = sys.B[:, input:input+1]
        new_D = sys.D[:, input:input+1]
        sys = StateSpace(sys.A, new_B, sys.C, new_D, sys.dt)

    return sys

def ss(*args, **kwargs):
    """ss(A, B, C, D[, dt])

    Create a state space system.

    The function accepts either 1, 4 or 5 parameters:

    ``ss(sys)``
        Convert a linear system into space system form. Always creates a
        new system, even if sys is already a StateSpace object.

    ``ss(A, B, C, D)``
        Create a state space system from the matrices of its state and
        output equations:

        .. math::
            \\dot x = A \\cdot x + B \\cdot u

            y = C \\cdot x + D \\cdot u

    ``ss(A, B, C, D, dt)``
        Create a discrete-time state space system from the matrices of
        its state and output equations:

        .. math::
            x[k+1] = A \\cdot x[k] + B \\cdot u[k]

            y[k] = C \\cdot x[k] + D \\cdot u[ki]

        The matrices can be given as *array like* data types or strings.
        Everything that the constructor of :class:`numpy.matrix` accepts is
        permissible here too.

    Parameters
    ----------
    sys: StateSpace or TransferFunction
        A linear system
    A: array_like or string
        System matrix
    B: array_like or string
        Control matrix
    C: array_like or string
        Output matrix
    D: array_like or string
        Feed forward matrix
    dt: If present, specifies the timebase of the system

    Returns
    -------
    out: :class:`StateSpace`
        The new linear system

    Raises
    ------
    ValueError
        if matrix sizes are not self-consistent

    See Also
    --------
    StateSpace
    tf
    ss2tf
    tf2ss

    Examples
    --------
    >>> # Create a StateSpace object from four "matrices".
    >>> sys1 = ss("1. -2; 3. -4", "5.; 7", "6. 8", "9.")

    >>> # Convert a TransferFunction to a StateSpace object.
    >>> sys_tf = tf([2.], [1., 3])
    >>> sys2 = ss(sys_tf)

    """

    if len(args) == 4 or len(args) == 5:
        return StateSpace(*args, **kwargs)
    elif len(args) == 1:
        from .xferfcn import TransferFunction
        sys = args[0]
        if isinstance(sys, StateSpace):
            return deepcopy(sys)
        elif isinstance(sys, TransferFunction):
            return tf2ss(sys)
        else:
            raise TypeError("ss(sys): sys must be a StateSpace or "
                            "TransferFunction object.  It is %s." % type(sys))
    else:
        raise ValueError("Needs 1, 4, or 5 arguments; received %i." % len(args))


def tf2ss(*args):
    """tf2ss(sys)

    Transform a transfer function to a state space system.

    The function accepts either 1 or 2 parameters:

    ``tf2ss(sys)``
        Convert a linear system into transfer function form. Always creates
        a new system, even if sys is already a TransferFunction object.

    ``tf2ss(num, den)``
        Create a transfer function system from its numerator and denominator
        polynomial coefficients.

        For details see: :func:`tf`

    Parameters
    ----------
    sys : LTI (StateSpace or TransferFunction)
        A linear system
    num : array_like, or list of list of array_like
        Polynomial coefficients of the numerator
    den : array_like, or list of list of array_like
        Polynomial coefficients of the denominator

    Returns
    -------
    out : StateSpace
        New linear system in state space form

    Raises
    ------
    ValueError
        if `num` and `den` have invalid or unequal dimensions, or if an
        invalid number of arguments is passed in
    TypeError
        if `num` or `den` are of incorrect type, or if sys is not a
        TransferFunction object

    See Also
    --------
    ss
    tf
    ss2tf

    Examples
    --------
    >>> num = [[[1., 2.], [3., 4.]], [[5., 6.], [7., 8.]]]
    >>> den = [[[9., 8., 7.], [6., 5., 4.]], [[3., 2., 1.], [-1., -2., -3.]]]
    >>> sys1 = tf2ss(num, den)

    >>> sys_tf = tf(num, den)
    >>> sys2 = tf2ss(sys_tf)

    """

    from .xferfcn import TransferFunction
    if len(args) == 2 or len(args) == 3:
        # Assume we were given the num, den
        return _convert_to_statespace(TransferFunction(*args))

    elif len(args) == 1:
        sys = args[0]
        if not isinstance(sys, TransferFunction):
            raise TypeError("tf2ss(sys): sys must be a TransferFunction "
                            "object.")
        return _convert_to_statespace(sys)
    else:
        raise ValueError("Needs 1 or 2 arguments; received %i." % len(args))


def rss(states=1, outputs=1, inputs=1, strictly_proper=False):
    """
    Create a stable *continuous* random state space object.

    Parameters
    ----------
    states : integer
        Number of state variables
    inputs : integer
        Number of system inputs
    outputs : integer
        Number of system outputs
    strictly_proper : bool, optional
        If set to 'True', returns a proper system (no direct term).  Default
        value is 'False'.

    Returns
    -------
    sys : StateSpace
        The randomly created linear system

    Raises
    ------
    ValueError
        if any input is not a positive integer

    See Also
    --------
    drss

    Notes
    -----
    If the number of states, inputs, or outputs is not specified, then the
    missing numbers are assumed to be 1.  The poles of the returned system
    will always have a negative real part.

    """

    return _rss_generate(states, inputs, outputs, 'c',
                         strictly_proper=strictly_proper)


def drss(states=1, outputs=1, inputs=1, strictly_proper=False):
    """
    Create a stable *discrete* random state space object.

    Parameters
    ----------
    states : integer
        Number of state variables
    inputs : integer
        Number of system inputs
    outputs : integer
        Number of system outputs

    Returns
    -------
    sys : StateSpace
        The randomly created linear system

    Raises
    ------
    ValueError
        if any input is not a positive integer

    See Also
    --------
    rss

    Notes
    -----
    If the number of states, inputs, or outputs is not specified, then the
    missing numbers are assumed to be 1.  The poles of the returned system
    will always have a magnitude less than 1.

    """

    return _rss_generate(states, inputs, outputs, 'd',
                         strictly_proper=strictly_proper)


def ssdata(sys):
    """
    Return state space data objects for a system

    Parameters
    ----------
    sys : LTI (StateSpace, or TransferFunction)
        LTI system whose data will be returned

    Returns
    -------
    (A, B, C, D): list of matrices
        State space data for the system
    """
    ss = _convert_to_statespace(sys)
    return ss.A, ss.B, ss.C, ss.D
