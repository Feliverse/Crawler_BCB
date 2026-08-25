from sqlalchemy import Table, Column, Integer, String, JSON, MetaData

metadata = MetaData()

metales = Table(
    "metales",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fecha", String, nullable=False, index=True),
    Column("moneda", String, nullable=True),
    Column("payload", JSON, nullable=False),
)
