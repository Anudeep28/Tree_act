from django import forms
from .models import StreetSearch

class StreetSearchForm(forms.ModelForm):
    query = forms.CharField(
        max_length=255,
        label='Enter a street name or city',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., Main Street, Boston or Oxford Street, London'
        })
    )
    
    class Meta:
        model = StreetSearch
        fields = ['query']
