import streamlit as st
from datetime import date, timedelta
import pandas as pd
import io

from crawler.collector import fetch_for_date
from crawler.parser import parse_table_rows
from crawler.storage_sqlalchemy import StorageSQLAlchemy
from crawler.config import DB_PATH


st.set_page_config(page_title="BCB Metales", layout="wide")
st.title("Validación del crawler BCB - Metales")

st.markdown("### Configuración")
col1, col2, col3 = st.columns(3)
with col1:
    start_date = st.date_input("Fecha inicial", value=date(2023, 1, 1))
with col2:
    end_date = st.date_input("Fecha final", value=date(2023, 1, 2))
with col3:
    use_playwright = st.checkbox("Usar navegador (fallback Playwright)", value=False)

if start_date > end_date:
    st.error("La fecha final debe ser mayor o igual que la inicial.")
    st.stop()

if st.button("Validar extracción", type="primary"):
    rows = []
    current = start_date
    total_days = (end_date - start_date).days + 1
    progress = st.progress(0)

    with st.spinner("Consultando fechas y parseando contenido..."):
        day_index = 0
        while current <= end_date:
            progress.progress((day_index + 1) / total_days)
            st.caption(f"Procesando {current.isoformat()} ...")
            try:
                html = fetch_for_date(current, use_playwright=use_playwright)
                parsed = parse_table_rows(html)
                for item in parsed:
                    item["fecha"] = current.isoformat()
                rows.extend(parsed)
            except Exception as exc:
                st.warning(f"No se pudo obtener {current.isoformat()}: {exc}")
            current += timedelta(days=1)
            day_index += 1

    if not rows:
        st.warning("No se encontraron filas con el rango indicado.")
        st.stop()

    df = pd.DataFrame(rows)

    if "fecha" not in df.columns:
        df["fecha"] = None
    if "Moneda" in df.columns:
        df["Moneda"] = df["Moneda"].astype(str)

    storage = StorageSQLAlchemy(DB_PATH)
    try:
        for fecha in df["fecha"].dropna().unique():
            subset = df[df["fecha"] == fecha]
            storage.insert_rows(fecha, subset.to_dict(orient="records"), moneda=None)
    finally:
        storage.engine.dispose()

    st.success(f"Se recuperaron {len(df)} registros en total y se guardaron en SQLite.")

    col_kpi_1, col_kpi_2, col_kpi_3 = st.columns(3)
    col_kpi_1.metric("Registros", len(df))
    col_kpi_2.metric("Desde", start_date.isoformat())
    col_kpi_3.metric("Hasta", end_date.isoformat())

    st.markdown("### Filtros")
    filters_col1, filters_col2 = st.columns(2)
    with filters_col1:
        if "Moneda" in df.columns:
            monedas = sorted(df["Moneda"].dropna().unique().tolist())
            moneda_sel = st.multiselect("Moneda", options=monedas, default=monedas)
            df = df[df["Moneda"].isin(moneda_sel)] if moneda_sel else df.head(0)
    with filters_col2:
        if "fecha" in df.columns:
            fechas = sorted(df["fecha"].dropna().unique().tolist())
            fecha_sel = st.multiselect("Fecha", options=fechas, default=fechas)
            df = df[df["fecha"].isin(fecha_sel)] if fecha_sel else df.head(0)

    if "Moneda" in df.columns:
        try:
            df["fecha"] = pd.to_datetime(df["fecha"]).dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    st.line_chart(df.groupby("fecha").size().reset_index(name="count"), x="fecha", y="count")
    st.dataframe(df, use_container_width=True, height=420)

    csv = df.to_csv(index=False)
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="BCB_Metales")
    excel_data = excel_buffer.getvalue()

    st.download_button(
        label="Descargar CSV",
        data=csv,
        file_name="bcb_metales.csv",
        mime="text/csv",
    )
    st.download_button(
        label="Descargar Excel",
        data=excel_data,
        file_name="bcb_metales.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
