from fastapi import APIRouter
from app.schemas.transaction import TransactionOut
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/api/transactions", tags=["transactions"])
service = TransactionService()


@router.get("", response_model=list[TransactionOut])
def list_transactions():
    return service.list_transactions()


@router.get("/{transaction_id}", response_model=TransactionOut)
def get_transaction(transaction_id: str):
    return service.get_transaction(transaction_id)
