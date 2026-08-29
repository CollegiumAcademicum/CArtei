from datetime import date

from django import forms
from django.db.models import Q

from app.models import Room, Tenant, TenantRoomAssignment
from app.tenant_access import EDITABLE_COLUMNS


class TenantForm(forms.ModelForm):
    # Model column is a plain CharField; declare EmailField so format is validated.
    email = forms.EmailField(required=True)

    class Meta:
        model = Tenant
        fields = EDITABLE_COLUMNS

    def __init__(self, *args, allowed_fields=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Native browser date picker (like the engagement surveys): <input type="date">.
        # Force ISO so existing values prefill and submissions parse under the de-de locale.
        for field in self.fields.values():
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(
                    attrs={"type": "date", "class": "ca-input"}, format="%Y-%m-%d"
                )
                field.input_formats = ["%Y-%m-%d"]
        allowed = set(allowed_fields or [])
        for name in list(self.fields):
            if name not in allowed:
                del self.fields[name]


class TenantCreateForm(forms.ModelForm):
    """Mietverwaltung adds a tenant manually, before an LDAP account exists —
    intranet_username / intranet_uuid stay NULL. Name + email required; the rest
    of the profile is filled in later on the detail page (model/DB defaults apply)."""

    email = forms.EmailField(required=True)
    create_ldap_account = forms.BooleanField(
        required=False, initial=False,
        label="Intranet-Account direkt anlegen",
    )

    class Meta:
        model = Tenant
        fields = ["first_name", "last_name", "email", "phone"]


class RoomFurnitureForm(forms.ModelForm):
    """Room editor for size + Ausstattung (Mietverwaltung + AG Werkstatt)."""

    class Meta:
        model = Room
        fields = ["size_sqm", "has_mattress", "has_bed", "has_table", "has_closet"]
        labels = {
            "size_sqm": "Größe (m²)", "has_mattress": "Matratze",
            "has_bed": "Bett", "has_table": "Tisch", "has_closet": "Schrank",
        }
        widgets = {"size_sqm": forms.NumberInput(attrs={"step": "0.01", "min": "0", "class": "ca-input"})}


class TenantRoomAssignmentForm(forms.ModelForm):
    class Meta:
        model = TenantRoomAssignment
        fields = [
            "room", "moved_in", "moved_out", "mailbox_key_received",
            "mailbox_key_returned", "is_sublet", "sublet_of_tenant",
            "key_received", "key_returned", "deposit_iban",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = Room.objects.select_related("wg__building").order_by(
            "wg__building__name", "wg__name", "name"
        )
        self.fields["room"].label_from_instance = lambda r: f"{r.wg.building.name} · {r.wg.name} · {r.name}"
        self.fields["sublet_of_tenant"].queryset = Tenant.objects.order_by("last_name", "first_name")
        self.fields["sublet_of_tenant"].required = False
        for field in self.fields.values():
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(
                    attrs={"type": "date", "class": "ca-input"}, format="%Y-%m-%d"
                )
                field.input_formats = ["%Y-%m-%d"]
            elif hasattr(field, "widget") and not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "ca-input")
        # Each existing assignment has its own hidden <form id="form-room-{pk}">
        # (per-assignment save/revert). The card's document upload/revoke <form>s
        # sit physically inside the card, so the assignment fields can't be nested
        # in the same form — associate them via the HTML5 form attribute instead.
        # The new-room form (no pk) is a normal wrapping <form>, so it needs no attr.
        if self.instance.pk:
            for field in self.fields.values():
                field.widget.attrs["form"] = f"form-room-{self.instance.pk}"

    def clean(self):
        cleaned = super().clean()
        room, source = cleaned.get("room"), cleaned.get("sublet_of_tenant")
        # "Untervermietet von" must actually rent the selected room (active assignment).
        if room and source:
            today = date.today()
            rents = (
                TenantRoomAssignment.objects.filter(room=room, tenant=source)
                .filter(Q(moved_out__isnull=True) | Q(moved_out__gt=today))
                .exists()
            )
            if not rents:
                self.add_error(
                    "sublet_of_tenant",
                    "Diese Person mietet das ausgewählte Zimmer nicht.",
                )
        return cleaned


class RoomAssignmentCreateForm(forms.ModelForm):
    """Create an assignment for a fixed room (WG detail): pick the tenant, the
    room comes from the page. Mirror of TenantRoomAssignmentForm with room↔tenant
    swapped; the room is passed in and set by the view before save."""

    class Meta:
        model = TenantRoomAssignment
        fields = [
            "tenant", "moved_in", "moved_out", "mailbox_key_received",
            "mailbox_key_returned", "is_sublet", "sublet_of_tenant",
            "key_received", "key_returned", "deposit_iban",
        ]

    def __init__(self, *args, room=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.room = room
        self.fields["tenant"].queryset = Tenant.objects.order_by("last_name", "first_name")
        self.fields["sublet_of_tenant"].queryset = Tenant.objects.order_by("last_name", "first_name")
        self.fields["sublet_of_tenant"].required = False
        for field in self.fields.values():
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(
                    attrs={"type": "date", "class": "ca-input"}, format="%Y-%m-%d"
                )
                field.input_formats = ["%Y-%m-%d"]
            elif not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "ca-input")

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("sublet_of_tenant")
        # Same rule as above, against the fixed room this card belongs to.
        if self.room and source:
            today = date.today()
            rents = (
                TenantRoomAssignment.objects.filter(room=self.room, tenant=source)
                .filter(Q(moved_out__isnull=True) | Q(moved_out__gt=today))
                .exists()
            )
            if not rents:
                self.add_error(
                    "sublet_of_tenant",
                    "Diese Person mietet das ausgewählte Zimmer nicht.",
                )
        return cleaned
