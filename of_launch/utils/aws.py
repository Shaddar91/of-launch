"""AWS helpers without a real backend yet: the current-state page reads mock ECS state."""


def get_ecs_state(environment, region=None):
    return [], 200
