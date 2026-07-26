from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas.dataset import DatasetListResponse, DatasetRecord


router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("", response_model=DatasetListResponse)
def list_datasets(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> DatasetListResponse:
    datasets = request.app.state.store.list_datasets(limit=limit)
    return DatasetListResponse(items=[DatasetRecord(**dataset) for dataset in datasets])


@router.get("/{dataset_id}", response_model=DatasetRecord)
def get_dataset(request: Request, dataset_id: str) -> DatasetRecord:
    dataset = request.app.state.store.get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return DatasetRecord(**dataset)

