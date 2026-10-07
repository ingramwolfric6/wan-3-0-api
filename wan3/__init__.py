"""Wan 3.0 video API client: text, frames, references and video edits on one async endpoint."""
from .client import MODEL, RATE, Shot, Wan3, Wan3Error, price

__all__ = ["MODEL", "RATE", "Shot", "Wan3", "Wan3Error", "price"]
__version__ = "0.3.0"
