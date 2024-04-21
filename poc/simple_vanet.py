import math
from typing import Optional

import mesa
import numpy as np
from matplotlib import pyplot as plt, patches
from mesa import Agent, Model
from mesa.space import ContinuousSpace, FloatCoordinate
from mesa.time import BaseScheduler

import VanetTraceLoader as vanetLoader

# Constants for the simulation, adjusted for demonstration
TIME_STEP_MS = 500  # Time step in milliseconds
TIME_STEP_S = TIME_STEP_MS / 1000.0  # Time step in seconds
VEHICLE_SPEED_FAST_MS = 60 * (1000 / 3600)  # 60 km/h in m/s

VEC_STATION_COLORS = {
    10001: "red",
    10002: "blue",
    10003: "orange",
    10004: "green",
}

GRID = vanetLoader.get_grid()
TRACES = vanetLoader.get_traces()


def distance(pos1, pos2):
    """Calculate the Euclidean distance between two positions."""
    x1, y1 = pos1
    x2, y2 = pos2
    return np.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


def is_moving_towards(vehicle_pos, vehicle_orientation, station_pos):
    # Convert vehicle orientation to radians for math functions
    rad = math.radians(vehicle_orientation)

    # Calculate direction vector of vehicle's movement
    vehicle_dir = (math.cos(rad), math.sin(rad))

    # Calculate vector from vehicle to station
    to_station_vec = (station_pos[0] - vehicle_pos[0], station_pos[1] - vehicle_pos[1])

    # Calculate dot product
    dot_product = vehicle_dir[0] * to_station_vec[0] + vehicle_dir[1] * to_station_vec[1]

    # Check if dot product is positive
    return dot_product > 0


class VehicleAgent(Agent):
    """A vehicle agent that follows a list of waypoints and calculates its angle."""

    def __init__(self, unique_id, model, trace: vanetLoader.VehicleTrace):
        super().__init__(unique_id, model)
        self.ts = 0
        self.trace_i = 0
        self.trace = trace
        self.active = False
        self.angle = 0
        self.station: Optional["VECStationAgent"] = None

        if trace.first_ts == 0:
            self.do_step(0)

    def do_step(self, ts):

        self.active = True
        state = self.trace.trace.iloc[self.trace_i]
        if state['timestep_time'] != ts and state['timestep_time'] != ts - 1:
            raise ValueError("Time step mismatch")

        if state['timestep_time'] == ts:
            return

        self.trace_i += 1
        state = self.trace.trace.iloc[self.trace_i]

        if state['timestep_time'] > ts:
            raise ValueError("Time step jumped to the future")
        if state['timestep_time'] < ts:
            raise ValueError("Time step still in the past")

        self.pos = (state['vehicle_x'], state['vehicle_y'])
        self.angle = state['vehicle_angle']
        print("Move to", self.pos, "with angle", self.angle)
        self.model.space.move_agent(self, self.pos)

    def step(self):
        self.ts += 1
        external_ts = int(self.ts * TIME_STEP_S)
        if self.trace.first_ts <= external_ts <= self.trace.last_ts:
            self.do_step(external_ts)
        if external_ts > self.trace.last_ts:
            self.active = False


class VECStationAgent(Agent):
    """A VEC station agent with a communication range."""

    def __init__(self, unique_id, model, position, range_m, capacity, neighbors=None):
        super().__init__(unique_id, model)
        self.pos = position
        self.range = range_m
        self.capacity = capacity
        self.neighbors = neighbors if neighbors else []
        self.vehicles = []
        self.distance_threshold = 0.7
        self.load_threshold = 0.7
        self.vehicle_distance = None

    @property
    def load(self):
        return len(self.vehicles)

    def step(self):

        # Only temporary for demonstration
        # self.vehicle_distance = distance(self.pos, self.model.vehicle.pos)

        for vehicle in list(self.vehicles):
            # Check if vehicle is exiting the station's range soon
            if not self.is_vehicle_exiting(vehicle):
                continue

            self.attempt_handover(vehicle)

    def attempt_handover(self, vehicle: VehicleAgent):
        # Try to find a neighbor station to hand over the vehicle
        # Sort neighbors by distance to vehicle divided by range
        # This will prioritize neighbors that are closer to the vehicle and have a larger range
        neighbors = [(distance(x.pos, vehicle.pos) / x.range, x) for x in self.neighbors if x != self]
        sorted_neighbors = sorted(neighbors, key=lambda x: x[0])

        for ratio, neighbor in sorted_neighbors:
            # If the ratio is greater than 1, the neighbor is too far away (and so are the rest)
            if ratio > 1:
                break

            if neighbor.load < neighbor.capacity and is_moving_towards(vehicle.pos, vehicle.angle, neighbor.pos):
                # Hand over the vehicle to the best neighbor
                self.vehicles.remove(vehicle)
                neighbor.vehicles.append(vehicle)
                vehicle.station = neighbor
                print(f"Vehicle {vehicle.unique_id} handed over to VEC station {neighbor.unique_id}")
                return

        # TODO What to do if handover is unavoidable (e.g. capacity is full)?

    def is_vehicle_exiting(self, vehicle: VehicleAgent):
        # Predict if the vehicle will exit the station's range soon
        # TODO create more precise logic, e.g. based on vehicle speed, distance and range
        return (distance(self.pos, vehicle.pos) > self.range * self.distance_threshold
                and not is_moving_towards(vehicle.pos, vehicle.angle, self.pos))

    def __repr__(self):
        return f"VECStation{self.unique_id}"


class VECModel(Model):
    """A model with a single vehicle following waypoints on a rectangular road layout."""

    def __init__(self, width, height, speed):
        super().__init__()
        self.width = width
        self.height = height

        self.space = ContinuousSpace(width, height, False)  # Non-toroidal space
        self.schedule = BaseScheduler(self)

        def vehicle_count_collector(a: Agent):
            if isinstance(a, VECStationAgent):
                return len(a.vehicles)
            return None

        self.datacollector = mesa.DataCollector(
            agent_reporters={"Distances": "vehicle_distance", "StationVehicleCount": vehicle_count_collector}
        )

        self.running = True

        self.agents_list = []

        # Define waypoints at the corners of the rectangular road layout
        waypoints_pos_offset = 5
        waypoints = [(waypoints_pos_offset, waypoints_pos_offset), (width - waypoints_pos_offset, waypoints_pos_offset),
                     (width - waypoints_pos_offset, height - waypoints_pos_offset),
                     (waypoints_pos_offset, height - waypoints_pos_offset)]
        self.waypoints = waypoints

        station_pos_offset = 5
        station_positions = [
            (waypoints[0][0] + station_pos_offset, waypoints[0][1] + station_pos_offset),
            (waypoints[1][0] - station_pos_offset, waypoints[1][1] + station_pos_offset),
            (waypoints[2][0] - station_pos_offset, waypoints[2][1] - station_pos_offset),
            (waypoints[3][0] + station_pos_offset, waypoints[3][1] - station_pos_offset)
        ]
        self.vec_stations = []
        for i, pos in enumerate(station_positions, start=1):
            station = VECStationAgent(10000 + i, self, pos, 45, 10)
            self.vec_stations.append(station)
            self.space.place_agent(station, pos)
            self.schedule.add(station)
            self.agents_list.append(station)

        for i in range(4):
            self.vec_stations[i].neighbors = [self.vec_stations[(i + 1) % 4], self.vec_stations[(i + 3) % 4]]

        vehicle_id = 1

        def spawn_vehicle(trace_id):
            nonlocal vehicle_id
            vehicle = VehicleAgent(vehicle_id, self, TRACES[trace_id])
            self.schedule.add(vehicle)
            self.agents_list.append(vehicle)

            self.space.place_agent(vehicle, pos)
            vehicle_id += 1

            station = min(self.vec_stations, key=lambda x: distance(x.pos, vehicle.pos))
            station.vehicles.append(vehicle)
            vehicle.station = station

            if trace_id == "VehicleFlowEastToNorth.0":
                self.vehicle = vehicle

        for trace_id in TRACES.keys():
            spawn_vehicle(trace_id)

        self.datacollector.collect(self)

    def step(self):
        self.schedule.step()
        self.datacollector.collect(self)


def main():
    # Configuration for demonstration
    road_width = 200  # meters
    road_height = 200  # meters
    vehicle_speed = VEHICLE_SPEED_FAST_MS

    # Initialize and run the model
    model = VECModel(road_width, road_height, vehicle_speed)
    output = []

    vehicle_positions = []  # For recording vehicle positions
    vehicle_angles = []  # For recording vehicle angles

    # render_distance_chart(model)

    # Run the simulation for 200 steps to observe the vehicle's movement and rotation
    for i in range(400):
        model.step()
        vehicle = model.vehicle
        if i % 20 == 0:  # Collect position and angle for every 20 steps
            output.append(f"Step {i}: Vehicle Position: {vehicle.pos}, Angle: {vehicle.angle:.2f}")
            vehicle_positions.append(vehicle.pos)
            vehicle_angles.append(vehicle.angle)

    print(*output, sep='\n')

    # Visualize the recorded vehicle positions and directions
    fig, ax = plt.subplots()

    # Plot grid with cmap gray
    ax.imshow(GRID, cmap='gray', extent=[0, road_width, 0, road_height])

    # road = patches.Polygon(model.waypoints, closed=True, fill=False, edgecolor='black', linewidth=2)
    # ax.add_patch(road)

    # Draw stations
    station_size = 6  # Size of the square

    for station in model.vec_stations:
        color = VEC_STATION_COLORS[station.unique_id]
        # Draw the station as a square
        lower_left_corner = (station.pos[0] - station_size / 2, station.pos[1] - station_size / 2)
        square = patches.Rectangle(lower_left_corner, station_size, station_size, color=color)
        ax.add_patch(square)

        # Draw the range as a dotted circle
        circle = plt.Circle(station.pos, station.range, color=color, fill=False, linestyle='dotted')
        ax.add_artist(circle)

    # Draw vehicles
    vehicle_length = 2  # Length of the vehicle arrow

    for position, angle in zip(vehicle_positions, vehicle_angles):
        x, y = position
        dx = vehicle_length * np.cos(np.radians(angle))
        dy = vehicle_length * np.sin(np.radians(angle))
        ax.arrow(x, y, dx, dy, head_width=1, head_length=1, fc='blue', ec='blue')

    ax.set_xlim(0, road_width)
    ax.set_ylim(0, road_height)
    # ax.set_aspect('equal')
    plt.xlabel('Distance (meters)')
    plt.ylabel('Distance (meters)')
    plt.title('Recorded Vehicle Movement on a Rectangular Road')
    plt.grid(True)
    plt.show()


if __name__ == "__main__":
    main()


def test_moving_towards():
    assert is_moving_towards((0, 0), 45, (1, 1)), "Vehicle should be moving towards the station"


def test_moving_away():
    assert not is_moving_towards((0, 0), 225, (1, 1)), "Vehicle should be moving away from the station"


def test_moving_orthogonal():
    assert not is_moving_towards((0, 0), 136, (1, 1)), "Vehicle should be moving orthogonal to the station"
    assert not is_moving_towards((0, 0), 314, (1, 1)), "Vehicle should be moving orthogonal to the station"


def test_moving_directly_towards():
    assert is_moving_towards((0, 0), 0, (10, 0)), "Vehicle should be moving directly towards the station on the x-axis"


def test_moving_directly_away():
    assert not is_moving_towards((10, 0), 180,
                                 (20, 0)), "Vehicle should be moving directly away from the station on the x-axis"
