from django import forms
from django.contrib.auth.models import User

from .models import TokenApi


class ProfiloForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {"first_name": "Nome", "last_name": "Cognome", "email": "Email"}
        widgets = {f: forms.TextInput(attrs={"class": "ui-input"}) for f in ["first_name", "last_name"]}
        widgets["email"] = forms.EmailInput(attrs={"class": "ui-input"})


class TokenApiForm(forms.ModelForm):
    class Meta:
        model = TokenApi
        fields = ["nome"]
        labels = {"nome": "Nome del token"}
        widgets = {"nome": forms.TextInput(attrs={"class": "ui-input", "placeholder": "es. integrazione adabox"})}
