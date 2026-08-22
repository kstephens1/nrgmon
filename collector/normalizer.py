from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class CounterState:
    last_energy_wh: float | None = None
    total_energy_wh: float = 0.0
    last_power_w: float | None = None
    last_timestamp: float | None = None


class EnergyNormalizer:
    def __init__(self, state_file: str):
        self.path = Path(state_file)
        self.states: dict[str, CounterState] = self._load()

    def _load(self) -> dict[str, CounterState]:
        try:
            raw = json.loads(self.path.read_text())
            return {key: CounterState(**value) for key, value in raw.items()}
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=self.path.parent, delete=False) as handle:
            json.dump({key: asdict(value) for key, value in self.states.items()}, handle)
            temporary_path = handle.name
        os.replace(temporary_path, self.path)

    def normalize(self, key: str, power_w: float, energy_wh: float | None, value_type: str, timestamp: float) -> float:
        state = self.states.setdefault(key, CounterState())
        if value_type == "cumulative":
            incoming = energy_wh if energy_wh is not None else 0.0
            if state.last_energy_wh is not None and incoming < state.last_energy_wh:
                state.total_energy_wh += state.last_energy_wh
            total = state.total_energy_wh + incoming
            state.last_energy_wh = incoming
        elif value_type == "daily_counter":
            incoming = energy_wh if energy_wh is not None else 0.0
            if state.last_energy_wh is not None:
                state.total_energy_wh += incoming - state.last_energy_wh if incoming >= state.last_energy_wh else incoming
            state.last_energy_wh = incoming
            total = state.total_energy_wh
        elif value_type == "derived_from_power":
            if state.last_power_w is not None and state.last_timestamp is not None:
                elapsed_hours = max(0.0, timestamp - state.last_timestamp) / 3600
                state.total_energy_wh += ((state.last_power_w + power_w) / 2) * elapsed_hours
            total = state.total_energy_wh
        else:
            raise ValueError(f"Unknown energy type: {value_type}")
        state.last_power_w = power_w
        state.last_timestamp = timestamp
        self._save()
        return total
