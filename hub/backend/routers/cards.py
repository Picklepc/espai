from fastapi import APIRouter, HTTPException

from ..config import CARDS_DIR
from ..registry.loader import scan_folder

router = APIRouter()


@router.get("/")
def list_cards():
    return scan_folder(CARDS_DIR, "card")


@router.get("/{card_name}")
def get_card(card_name: str):
    all_cards = scan_folder(CARDS_DIR, "card")
    for c in all_cards:
        if c.get("name") == card_name or c.get("_folder") == card_name:
            return c
    raise HTTPException(404, f"Card {card_name!r} not found")
