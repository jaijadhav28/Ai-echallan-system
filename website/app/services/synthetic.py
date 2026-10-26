"""Synthetic traffic source used by DEMO CAMERA MODE.

Not every student has three IP cameras on the desk, and a freshly cloned repo has
no sample video either. This module procedurally renders a moving traffic scene
with OpenCV so Live Monitoring shows real, animated frames out of the box.

Each rendered frame also carries *ground truth* describing the scripted vehicles
(rider count, helmet, direction, dangerous container). The detection service uses
that ground truth only for synthetic cameras, and stamps the resulting records
with ``detector="DEMO_SIMULATOR"`` so simulated detections are never presented as
real AI results.
"""

from __future__ import annotations

import random
import time

import cv2
import numpy as np

# Native 4K (3840×2160). Geometry is the old 960×540 scene scaled by 4.
SCALE = 4
WIDTH, HEIGHT = 960 * SCALE, 540 * SCALE
ROAD_TOP = 170 * SCALE
LANE_HEIGHT = 85 * SCALE
FIRST_LANE_Y = ROAD_TOP + 55 * SCALE
LANE_COUNT = 4

_PLATE_STATES = ["KA", "MH", "TN", "KL", "AP", "TS", "DL", "GJ"]
_PLATE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def _random_plate() -> str:
    return (
        f"{random.choice(_PLATE_STATES)}{random.randint(10, 99)}"
        f"{random.choice(_PLATE_LETTERS)}{random.choice(_PLATE_LETTERS)}"
        f"{random.randint(1000, 9999)}"
    )


class _Vehicle:
    """A scripted two-wheeler or car travelling across the frame."""

    def __init__(self, lane: int, direction: int, violation_bias: float):
        self.lane = lane
        self.direction = direction  # +1 -> left to right, -1 -> right to left
        self.speed = random.uniform(2.6, 5.4) * SCALE
        self.plate = _random_plate()
        self.is_bike = random.random() < 0.78

        if self.is_bike:
            self.riders = 3 if random.random() < violation_bias * 0.55 else random.choice([1, 2])
            self.helmets = [random.random() > violation_bias for _ in range(self.riders)]
            self.carries_container = random.random() < violation_bias * 0.35
        else:
            self.riders = 1
            self.helmets = [True]
            self.carries_container = random.random() < violation_bias * 0.2

        self.length = (70 if self.is_bike else 120) * SCALE
        self.x = -self.length if direction > 0 else WIDTH + self.length
        self.y = FIRST_LANE_Y + lane * LANE_HEIGHT
        self.colour = random.choice(
            [(60, 60, 70), (150, 60, 40), (40, 90, 140), (90, 90, 95), (30, 110, 70)]
        )

    @property
    def wrong_side(self) -> bool:
        """Lanes 0/1 legally flow right, lanes 2/3 legally flow left."""
        expected = 1 if self.lane < 2 else -1
        return self.direction != expected

    def advance(self) -> None:
        self.x += self.speed * self.direction

    def off_screen(self) -> bool:
        return self.x < -self.length * 2 or self.x > WIDTH + self.length * 2

    def bounding_box(self) -> tuple[int, int, int, int]:
        height = (62 if self.is_bike else 54) * SCALE
        return int(self.x), int(self.y - height), int(self.length), int(height + 24 * SCALE)

    def ground_truth(self) -> dict:
        return {
            "plate": self.plate,
            "vehicle_type": "two wheeler" if self.is_bike else "car",
            "riders": self.riders,
            "helmets_worn": sum(1 for worn in self.helmets if worn),
            "no_helmet": any(not worn for worn in self.helmets),
            "triple_riding": self.is_bike and self.riders >= 3,
            "wrong_side": self.wrong_side,
            "carries_container": self.carries_container,
            "box": list(self.bounding_box()),
        }


class SyntheticTrafficSource:
    """Renders an endless animated traffic scene."""

    def __init__(self, camera_label: str = "DEMO", violation_bias: float = 0.45):
        self.camera_label = camera_label
        self.violation_bias = max(0.05, min(violation_bias, 0.9))
        self.vehicles: list[_Vehicle] = []
        self.offset = 0
        self.started = time.time()
        random.seed()

    # -------------------------------------------------------------- #
    def _spawn(self) -> None:
        if len(self.vehicles) >= 7 or random.random() > 0.09:
            return
        lane = random.randint(0, LANE_COUNT - 1)
        direction = 1 if lane < 2 else -1
        if random.random() < self.violation_bias * 0.3:
            direction *= -1  # scripted wrong-side vehicle
        self.vehicles.append(_Vehicle(lane, direction, self.violation_bias))

    def _draw_background(self, frame: np.ndarray) -> None:
        s = SCALE
        frame[:ROAD_TOP] = (150, 130, 110)
        cv2.rectangle(frame, (0, ROAD_TOP - 40 * s), (WIDTH, ROAD_TOP), (95, 120, 85), -1)
        frame[ROAD_TOP:] = (68, 68, 72)

        # lane separators, scrolling to convey motion
        centre_y = FIRST_LANE_Y + LANE_HEIGHT * 2 - LANE_HEIGHT // 2
        for lane in range(1, LANE_COUNT):
            lane_y = FIRST_LANE_Y + lane * LANE_HEIGHT - LANE_HEIGHT // 2
            if lane_y == centre_y:
                continue
            for x in range(-60 * s + self.offset % (90 * s), WIDTH, 90 * s):
                cv2.line(frame, (x, lane_y), (x + 45 * s, lane_y), (215, 215, 215), 3 * s)
        cv2.line(frame, (0, centre_y), (WIDTH, centre_y), (0, 210, 235), 2 * s)
        cv2.rectangle(frame, (0, HEIGHT - 12 * s), (WIDTH, HEIGHT), (200, 200, 200), -1)

        # roadside buildings for visual context
        for index in range(7):
            x = index * 145 * s + (self.offset // (6 * s)) % (145 * s) - 145 * s
            height = 60 * s + ((index * 37) % 70) * s
            cv2.rectangle(
                frame,
                (x, ROAD_TOP - 40 * s - height),
                (x + 110 * s, ROAD_TOP - 40 * s),
                (120, 110, 105),
                -1,
            )
            for row in range(height // (26 * s)):
                for column in range(3):
                    cv2.rectangle(
                        frame,
                        (x + 14 * s + column * 32 * s, ROAD_TOP - 60 * s - row * 26 * s),
                        (x + 32 * s + column * 32 * s, ROAD_TOP - 46 * s - row * 26 * s),
                        (185, 195, 205),
                        -1,
                    )

    def _draw_vehicle(self, frame: np.ndarray, vehicle: _Vehicle) -> None:
        s = SCALE
        x, y = int(vehicle.x), int(vehicle.y)
        length = vehicle.length

        if vehicle.is_bike:
            cv2.circle(frame, (x + 14 * s, y + 12 * s), 13 * s, (25, 25, 25), -1)
            cv2.circle(frame, (x + length - 14 * s, y + 12 * s), 13 * s, (25, 25, 25), -1)
            cv2.rectangle(
                frame, (x + 12 * s, y - 14 * s), (x + length - 12 * s, y + 6 * s), vehicle.colour, -1
            )

            for index in range(vehicle.riders):
                rider_x = x + 20 * s + index * 18 * s
                cv2.ellipse(
                    frame, (rider_x, y - 30 * s), (9 * s, 20 * s), 0, 0, 360, (55, 65, 120), -1
                )  # torso
                head_centre = (rider_x, y - 54 * s)
                if vehicle.helmets[index]:
                    cv2.circle(frame, head_centre, 11 * s, (35, 200, 235), -1)  # helmet
                    cv2.circle(frame, head_centre, 11 * s, (20, 20, 20), 2 * s)
                    cv2.ellipse(
                        frame, head_centre, (11 * s, 11 * s), 0, 200, 340, (30, 30, 30), 3 * s
                    )
                else:
                    cv2.circle(frame, head_centre, 10 * s, (155, 185, 215), -1)  # bare head
                    cv2.ellipse(
                        frame, head_centre, (10 * s, 10 * s), 0, 190, 350, (40, 35, 30), -1
                    )

            if vehicle.carries_container:
                cv2.rectangle(
                    frame, (x + 6 * s, y - 40 * s), (x + 26 * s, y - 12 * s), (40, 40, 205), -1
                )
                cv2.rectangle(
                    frame, (x + 6 * s, y - 40 * s), (x + 26 * s, y - 12 * s), (20, 20, 120), 2 * s
                )
                cv2.putText(
                    frame,
                    "LPG",
                    (x + 5 * s, y - 44 * s),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45 * s,
                    (30, 30, 220),
                    s,
                )
        else:
            cv2.rectangle(frame, (x, y - 44 * s), (x + length, y + 6 * s), vehicle.colour, -1)
            cv2.rectangle(
                frame,
                (x + 22 * s, y - 40 * s),
                (x + length - 22 * s, y - 18 * s),
                (190, 205, 215),
                -1,
            )
            cv2.circle(frame, (x + 24 * s, y + 10 * s), 13 * s, (25, 25, 25), -1)
            cv2.circle(frame, (x + length - 24 * s, y + 10 * s), 13 * s, (25, 25, 25), -1)

        # number plate - readable by a real ANPR call when a key is configured
        plate_width = 94 * s
        plate_x = max(x + (length - plate_width if vehicle.direction > 0 else 0), 0)
        cv2.rectangle(
            frame,
            (plate_x, y + 14 * s),
            (plate_x + plate_width, y + 32 * s),
            (245, 245, 245),
            -1,
        )
        cv2.rectangle(
            frame,
            (plate_x, y + 14 * s),
            (plate_x + plate_width, y + 32 * s),
            (30, 30, 30),
            s,
        )
        cv2.putText(
            frame,
            vehicle.plate,
            (plate_x + 4 * s, y + 28 * s),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42 * s,
            (10, 10, 10),
            s,
        )

    # -------------------------------------------------------------- #
    def read(self) -> tuple[np.ndarray, dict]:
        """Render the next frame and return it with its ground truth."""
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        self.offset += 6 * SCALE
        self._spawn()
        self._draw_background(frame)

        for vehicle in list(self.vehicles):
            vehicle.advance()
            if vehicle.off_screen():
                self.vehicles.remove(vehicle)
                continue
            self._draw_vehicle(frame, vehicle)

        visible = [
            vehicle
            for vehicle in self.vehicles
            if -20 * SCALE < vehicle.x < WIDTH - vehicle.length + 20 * SCALE
        ]
        ground_truth = {
            "source": "SYNTHETIC",
            "vehicle_count": len(visible),
            "vehicles": [vehicle.ground_truth() for vehicle in visible],
        }
        return frame, ground_truth
