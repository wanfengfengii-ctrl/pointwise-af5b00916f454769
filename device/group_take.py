from contextlib import closing

from device.joint_take import ensure_joint_schema, held_generations
from device.latch import clear_active_generations, read_active
from device.store import open_device_store
from device.take_history import DeviceOutcome, TakeBinding, TakenGroup, read_take_record, write_take_record


class DeviceExchangeInterrupted(Exception):
    """The caller could not confirm a device command or its reply."""


def take_group(path, binding: TakeBinding) -> DeviceOutcome:
    with closing(open_device_store(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        ensure_joint_schema(db)
        outcome = read_take_record(db, binding)
        if outcome.state != 'pending':
            return outcome

        channels = tuple(channel for channel, _ in binding.generations)
        active = read_active(db, channels)
        actual = tuple((row.channel, row.generation) for row in active.values())
        if actual == binding.generations:
            if held_generations(db, binding.generations):
                # A joint inspection holds these generations; the ordinary
                # order stays resumable instead of turning invalid.
                return DeviceOutcome(binding, 'pending')
            group = TakenGroup(binding, tuple(active.values()))
            clear_active_generations(db, binding.generations)
            outcome = DeviceOutcome(binding, 'taken', group)
        else:
            outcome = DeviceOutcome(binding, 'invalid')
        write_take_record(db, outcome)
        return outcome
