from django import forms
from django.contrib.auth.models import User


class ProfiloForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {"first_name": "Nome", "last_name": "Cognome", "email": "Email"}
        widgets = {f: forms.TextInput(attrs={"class": "ui-input"}) for f in ["first_name", "last_name"]}
        widgets["email"] = forms.EmailInput(attrs={"class": "ui-input"})
