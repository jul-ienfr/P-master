# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""TimesFM 2p5 base implementation."""

import collections
import dataclasses
from typing import Any, Callable, Sequence

import numpy as np

from .. import configs

ResidualBlockConfig = configs.ResidualBlockConfig
StackedTransformersConfig = configs.StackedTransformersConfig
TransformerConfig = configs.TransformerConfig
ForecastConfig = configs.ForecastConfig
Category = int | str
XRegMode = str


def strip_leading_nans(arr):
  """Removes contiguous NaN values from the beginning of a NumPy array."""

  isnan = np.isnan(arr)
  first_valid_index = np.argmax(~isnan)
  return arr[first_valid_index:]


def linear_interpolation(arr):
  """Performs linear interpolation to fill NaN values in a 1D numpy array."""

  nans = np.isnan(arr)
  if not np.any(nans):
    return arr

  def x(z):
    return z.nonzero()[0]

  nans_indices = x(nans)
  non_nans_indices = x(~nans)
  non_nans_values = arr[~nans]

  try:
    arr[nans] = np.interp(nans_indices, non_nans_indices, non_nans_values)
  except ValueError:
    if non_nans_values.size:
      mu = np.nanmean(arr)
    else:
      mu = 0.0
    arr = np.where(np.isfinite(arr), arr, mu)
  return arr


@dataclasses.dataclass(frozen=True)
class TimesFM_2p5_200M_Definition:
  """Framework-agnostic config of TimesFM 2.5."""

  context_limit = 16384
  input_patch_len: int = 32
  output_patch_len: int = 128
  output_quantile_len: int = 1024
  quantiles: list[float] = dataclasses.field(
    default_factory=lambda: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
  )
  decode_index: int = 5
  tokenizer: ResidualBlockConfig = ResidualBlockConfig(
    input_dims=64,
    hidden_dims=1280,
    output_dims=1280,
    use_bias=True,
    activation="swish",
  )
  stacked_transformers: StackedTransformersConfig = StackedTransformersConfig(
    num_layers=20,
    transformer=TransformerConfig(
      model_dims=1280,
      hidden_dims=1280,
      num_heads=16,
      attention_norm="rms",
      feedforward_norm="rms",
      qk_norm="rms",
      use_bias=False,
      use_rotary_position_embeddings=True,
      ff_activation="swish",
      fuse_qkv=True,
    ),
  )
  output_projection_point: ResidualBlockConfig = ResidualBlockConfig(
    input_dims=1280,
    hidden_dims=1280,
    output_dims=1280,
    use_bias=False,
    activation="swish",
  )
  output_projection_quantiles: ResidualBlockConfig = ResidualBlockConfig(
    input_dims=1280,
    hidden_dims=1280,
    output_dims=10240,
    use_bias=False,
    activation="swish",
  )


class TimesFM_2p5:
  """Abstract base class for TimesFM models."""

  forecast_config: ForecastConfig | None = None
  compiled_decode: Callable[..., Any] | None = None
  global_batch_size: int = 0

  def load_checkpoint(self, path: str):
    raise NotImplementedError()

  def compile(self, forecast_config: ForecastConfig | None = None):
    raise NotImplementedError()

  def forecast(
    self, horizon: int, inputs: list[np.ndarray]
  ) -> tuple[np.ndarray, np.ndarray]:
    if self.compiled_decode is None:
      raise RuntimeError("Model is not compiled. Please call compile() first.")

    assert self.global_batch_size > 0
    assert self.forecast_config is not None

    context = self.forecast_config.max_context
    num_inputs = len(inputs)
    padded_inputs = list(inputs)
    if (w := num_inputs % self.global_batch_size) != 0:
      padded_inputs += [np.array([0.0] * 3)] * (self.global_batch_size - w)

    output_points = []
    output_quantiles = []
    values = []
    masks = []
    idx = 0
    for each_input in padded_inputs:
      value = linear_interpolation(strip_leading_nans(np.array(each_input, dtype=float)))
      if (w := len(value)) >= context:
        value = value[-context:]
        mask = np.zeros_like(value, dtype=bool)
      else:
        mask = np.array([True] * (context - w) + [False] * w)
        value = np.pad(value, (context - w, 0), "constant", constant_values=0.0)
      values.append(value)
      masks.append(mask)
      idx += 1
      if idx == self.global_batch_size:
        idx = 0
        point_forecast, quantile_forecast = self.compiled_decode(horizon, values, masks)
        output_points.append(point_forecast)
        output_quantiles.append(quantile_forecast)
        values = []
        masks = []

    output_points = np.concatenate(output_points, axis=0)
    output_quantiles = np.concatenate(output_quantiles, axis=0)
    return output_points[:num_inputs], output_quantiles[:num_inputs]

  def forecast_with_covariates(
    self,
    inputs: list[Sequence[float]],
    dynamic_numerical_covariates: dict[str, Sequence[Sequence[float]]] | None = None,
    dynamic_categorical_covariates: (
      dict[str, Sequence[Sequence[Category]]] | None
    ) = None,
    static_numerical_covariates: dict[str, Sequence[float]] | None = None,
    static_categorical_covariates: dict[str, Sequence[Category]] | None = None,
    xreg_mode: XRegMode = "xreg + timesfm",
    normalize_xreg_target_per_input: bool = True,
    ridge: float = 0.0,
    max_rows_per_col: int = 0,
    force_on_cpu: bool = False,
  ):
    if self.forecast_config is None:
      raise ValueError("Model is not compiled. Please call compile() first.")
    if not self.forecast_config.return_backcast:
      raise ValueError(
        "For XReg, `return_backcast` must be set to True in the forecast config. Please recompile the model."
      )

    from ..utils import xreg_lib

    if not (
      dynamic_numerical_covariates
      or dynamic_categorical_covariates
      or static_numerical_covariates
      or static_categorical_covariates
    ):
      raise ValueError(
        "At least one covariate set must be provided for forecast_with_covariates()."
      )

    input_lens, train_lens, test_lens = [], [], []

    for i, input_ts in enumerate(inputs):
      input_len = len(input_ts)
      input_lens.append(input_len)

      if xreg_mode == "timesfm + xreg":
        train_lens.append(max(0, input_len - self.model.p))
      elif xreg_mode == "xreg + timesfm":
        train_lens.append(input_len)
      else:
        raise ValueError(f"Unsupported mode: {xreg_mode}")

      if dynamic_numerical_covariates:
        test_lens.append(
          len(list(dynamic_numerical_covariates.values())[0][i]) - input_len
        )
      elif dynamic_categorical_covariates:
        test_lens.append(
          len(list(dynamic_categorical_covariates.values())[0][i]) - input_len
        )
      else:
        test_lens.append(self.forecast_config.max_horizon)

      if test_lens[-1] > self.forecast_config.max_horizon:
        raise ValueError(
          "Forecast horizon inferred from covariates exceeds the compiled max_horizon."
        )

    train_dynamic_numerical_covariates = collections.defaultdict(list)
    test_dynamic_numerical_covariates = collections.defaultdict(list)
    train_dynamic_categorical_covariates = collections.defaultdict(list)
    test_dynamic_categorical_covariates = collections.defaultdict(list)
    for covariates, train_covariates, test_covariates in (
      (
        dynamic_numerical_covariates,
        train_dynamic_numerical_covariates,
        test_dynamic_numerical_covariates,
      ),
      (
        dynamic_categorical_covariates,
        train_dynamic_categorical_covariates,
        test_dynamic_categorical_covariates,
      ),
    ):
      if not covariates:
        continue
      for covariate_name, covariate_values in covariates.items():
        for input_len, train_len, covariate_value in zip(
          input_lens, train_lens, covariate_values
        ):
          train_covariates[covariate_name].append(
            covariate_value[(input_len - train_len) : input_len]
          )
          test_covariates[covariate_name].append(covariate_value[input_len:])

    if xreg_mode == "timesfm + xreg":
      point_outputs, quantile_outputs = self.forecast(
        horizon=self.forecast_config.max_horizon,
        inputs=inputs,
      )
      targets = [
        (
          np.array(input_ts)[-train_len:]
          - point_output[: -self.forecast_config.max_horizon][-train_len:]
        )
        for input_ts, point_output, train_len in zip(inputs, point_outputs, train_lens)
      ]
      per_instance_stats = None
      if normalize_xreg_target_per_input:
        targets, per_instance_stats = xreg_lib.normalize(targets)
      xregs = xreg_lib.BatchedInContextXRegLinear(
        targets=targets,
        train_lens=train_lens,
        test_lens=test_lens,
        train_dynamic_numerical_covariates=train_dynamic_numerical_covariates,
        test_dynamic_numerical_covariates=test_dynamic_numerical_covariates,
        train_dynamic_categorical_covariates=train_dynamic_categorical_covariates,
        test_dynamic_categorical_covariates=test_dynamic_categorical_covariates,
        static_numerical_covariates=static_numerical_covariates,
        static_categorical_covariates=static_categorical_covariates,
      ).fit(
        ridge=ridge,
        one_hot_encoder_drop=None if ridge > 0 else "first",
        max_rows_per_col=max_rows_per_col,
        force_on_cpu=force_on_cpu,
        debug_info=False,
        assert_covariates=True,
        assert_covariate_shapes=True,
      )
      if normalize_xreg_target_per_input:
        xregs = xreg_lib.renormalize(xregs, per_instance_stats)
      xregs = np.array(xregs)
      new_point_outputs = [
        (point_output[-self.forecast_config.max_horizon :][:test_len] + xreg)
        for point_output, test_len, xreg in zip(point_outputs, test_lens, xregs)
      ]
      new_quantile_outputs = [
        (
          quantile_output[-self.forecast_config.max_horizon :][:test_len]
          + xreg[..., None]
        )
        for quantile_output, test_len, xreg in zip(quantile_outputs, test_lens, xregs)
      ]
    else:
      targets = [
        np.array(input_ts)[-train_len:]
        for input_ts, train_len in zip(inputs, train_lens)
      ]
      per_instance_stats = None
      if normalize_xreg_target_per_input:
        targets, per_instance_stats = xreg_lib.normalize(targets)
      xregs, xregs_on_context, _, _, _ = xreg_lib.BatchedInContextXRegLinear(
        targets=targets,
        train_lens=train_lens,
        test_lens=test_lens,
        train_dynamic_numerical_covariates=train_dynamic_numerical_covariates,
        test_dynamic_numerical_covariates=test_dynamic_numerical_covariates,
        train_dynamic_categorical_covariates=train_dynamic_categorical_covariates,
        test_dynamic_categorical_covariates=test_dynamic_categorical_covariates,
        static_numerical_covariates=static_numerical_covariates,
        static_categorical_covariates=static_categorical_covariates,
      ).fit(
        ridge=ridge,
        one_hot_encoder_drop=None if ridge > 0 else "first",
        max_rows_per_col=max_rows_per_col,
        force_on_cpu=force_on_cpu,
        debug_info=True,
        assert_covariates=True,
        assert_covariate_shapes=True,
      )
      point_outputs, quantile_outputs = self.forecast(
        horizon=self.forecast_config.max_horizon,
        inputs=[
          target - xreg_on_context
          for target, xreg_on_context in zip(targets, xregs_on_context)
        ],
      )
      new_point_outputs = [
        (point_output[-self.forecast_config.max_horizon :][:test_len] + xreg)
        for point_output, test_len, xreg in zip(point_outputs, test_lens, xregs)
      ]
      new_quantile_outputs = [
        (
          quantile_output[-self.forecast_config.max_horizon :][:test_len]
          + xreg[..., None]
        )
        for quantile_output, test_len, xreg in zip(quantile_outputs, test_lens, xregs)
      ]
      if normalize_xreg_target_per_input:
        new_point_outputs = xreg_lib.renormalize(new_point_outputs, per_instance_stats)
        new_quantile_outputs = xreg_lib.renormalize(
          new_quantile_outputs,
          per_instance_stats,
        )

    return new_point_outputs, new_quantile_outputs
