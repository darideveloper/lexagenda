"""The calendar rule (PLAN §7.1): SEQUENCE moves on create, move, cancel and re-address.

Every writer of an appointment goes through here, so no call site can forget the bump and
a recompute of the day's travel blocks never touches the calendar identity.
"""

from apps.agenda.models import Appointment


def create(**fields):
    appointment = Appointment.objects.create(**fields)
    return bump(appointment)


def reschedule(appointment, starts_at):
    if appointment.starts_at == starts_at:
        return appointment
    appointment.starts_at = starts_at
    appointment.save(update_fields=["starts_at", "updated_at"])
    return bump(appointment)


def cancel(appointment):
    if appointment.status == Appointment.CANCELLED:
        return appointment
    appointment.status = Appointment.CANCELLED
    appointment.save(update_fields=["status", "updated_at"])
    return bump(appointment)


def readdress(appointment, address, location_name=""):
    if (appointment.address, appointment.location_name) == (address, location_name):
        return appointment
    appointment.address = address
    appointment.location_name = location_name
    appointment.address_source = Appointment.MANUAL
    appointment.save(update_fields=["address", "location_name", "address_source", "updated_at"])
    return bump(appointment)


def bump(appointment):
    """Exactly one higher, in the only place ics_sequence is ever written."""
    appointment.ics_sequence += 1
    appointment.save(update_fields=["ics_sequence", "updated_at"])
    _mail_invite(appointment)
    return appointment


def _mail_invite(appointment):
    from apps.integrations import mail  # uploaded after the models; keeps the app graph acyclic

    mail.invite(appointment)
