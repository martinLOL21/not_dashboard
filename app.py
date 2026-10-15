import streamlit as st
from influxdb_client import InfluxDBClient
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone

# ---------------------------
# CONFIGURACIÓN
# ---------------------------
url = "https://us-east-1-1.aws.cloud2.influxdata.com"

# Recomendado: guardar las credenciales en .streamlit/secrets.toml
token = st.secrets["influxdb"]["token"]
org = "miguelcmo"
bucket = "iot_telemetry_data"

# ---------------------------
# STREAMLIT UI
# ---------------------------
st.set_page_config(
    page_title="IoT Dashboard",
    page_icon="🌡️",
    layout="wide"
)

st.title("🌡️ IoT Telemetry Dashboard")
st.markdown(
    "Monitoreo interactivo de temperatura y humedad"
)

st.sidebar.header("Configuración")

# Seleccionar cuántas horas hacia atrás se quieren consultar
rango_horas = st.sidebar.slider(
    "Rango de horas (hacia atrás desde ahora)",
    min_value=1,
    max_value=168,
    value=(0, 24),
    help="Selecciona el intervalo temporal. "
         "El extremo derecho representa las horas más recientes."
)

# El slider puede comenzar en 0 para representar el momento actual.
# Se interpreta como: desde hace N horas hasta hace M horas.
horas_recientes, horas_antiguas = rango_horas

# Evitar un intervalo de cero horas
if horas_recientes == horas_antiguas:
    st.sidebar.warning("Selecciona un intervalo de tiempo válido.")

# Resolución de las gráficas
resolucion = st.sidebar.selectbox(
    "Agrupar datos por",
    ["1 hora", "30 minutos", "10 minutos"],
    index=0
)

intervalos = {
    "1 hora": "1h",
    "30 minutos": "30min",
    "10 minutos": "10min"
}

# Actualización automática
refresh = st.sidebar.slider(
    "Auto-refresh (segundos)",
    min_value=0,
    max_value=60,
    value=10
)

# ---------------------------
# CONSULTA A INFLUXDB
# ---------------------------
@st.cache_data(ttl=10)
def load_data(start_iso, end_iso):
    with InfluxDBClient(
        url=url,
        token=token,
        org=org
    ) as client:

        query_api = client.query_api()

        query = f'''
        from(bucket: "{bucket}")
          |> range(
              start: time(v: "{start_iso}"),
              stop: time(v: "{end_iso}")
          )
          |> filter(fn: (r) =>
              r["_field"] == "temperature" or
              r["_field"] == "humidity"
          )
          |> pivot(
              rowKey: ["_time"],
              columnKey: ["_field"],
              valueColumn: "_value"
          )
          |> keep(columns: [
              "_time",
              "temperature",
              "humidity"
          ])
          |> sort(columns: ["_time"])
        '''

        result = query_api.query_data_frame(query)

    if isinstance(result, list):
        frames = [
            frame for frame in result
            if frame is not None and not frame.empty
        ]

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
    else:
        df = result

    if df.empty or "_time" not in df.columns:
        return pd.DataFrame()

    # Limpiar los datos
    df["_time"] = pd.to_datetime(df["_time"], utc=True)

    for col in ["temperature", "humidity"]:
        if col not in df.columns:
            df[col] = float("nan")

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    df = df.dropna(
        subset=["temperature", "humidity"],
        how="all"
    )

    df = df.sort_values("_time")

    return df


# ---------------------------
# SELECCIÓN TEMPORAL
# ---------------------------
ahora = datetime.now(timezone.utc)

# El slider entrega (horas recientes, horas antiguas).
# Ejemplo: (0, 24) significa las últimas 24 horas.
horas_recientes, horas_antiguas = rango_horas

fecha_inicio = ahora - timedelta(hours=horas_antiguas)
fecha_fin = ahora - timedelta(hours=horas_recientes)

if fecha_inicio >= fecha_fin:
    st.warning(
        "El intervalo seleccionado no es válido. "
        "Selecciona un rango mayor que cero."
    )
    st.stop()

start_iso = fecha_inicio.isoformat()
end_iso = fecha_fin.isoformat()

st.caption(
    f"Periodo consultado: "
    f"{fecha_inicio.strftime('%d/%m/%Y %H:%M UTC')} — "
    f"{fecha_fin.strftime('%d/%m/%Y %H:%M UTC')}"
)

df = load_data(start_iso, end_iso)


# ---------------------------
# MÉTRICAS
# ---------------------------
if not df.empty:

    col1, col2, col3, col4 = st.columns(4)

    temperatura_actual = df["temperature"].dropna()
    humedad_actual = df["humidity"].dropna()

    col1.metric(
        "🌡️ Última temperatura",
        f"{temperatura_actual.iloc[-1]:.2f} °C"
        if not temperatura_actual.empty else "N/D"
    )

    col2.metric(
        "💧 Última humedad",
        f"{humedad_actual.iloc[-1]:.2f} %"
        if not humedad_actual.empty else "N/D"
    )

    col3.metric(
        "📊 Temperatura promedio",
        f"{temperatura_actual.mean():.2f} °C"
        if not temperatura_actual.empty else "N/D"
    )

    col4.metric(
        "📊 Humedad promedio",
        f"{humedad_actual.mean():.2f} %"
        if not humedad_actual.empty else "N/D"
    )

    st.divider()

    # ---------------------------
    # AGRUPACIÓN TEMPORAL
    # ---------------------------
    df_grafica = (
        df.set_index("_time")[["temperature", "humidity"]]
        .resample(intervalos[resolucion])
        .mean()
        .dropna(how="all")
        .reset_index()
    )

    # ---------------------------
    # GRÁFICA DE TEMPERATURA
    # ---------------------------
    st.subheader("🌡️ Temperatura por intervalo")

    fig_temp = px.bar(
        df_grafica,
        x="_time",
        y="temperature",
        title=f"Temperatura promedio — {resolucion}",
        labels={
            "_time": "Fecha y hora",
            "temperature": "Temperatura (°C)"
        },
        color_discrete_sequence=["#EF553B"]
    )

    fig_temp.update_layout(
        xaxis_title="Fecha y hora",
        yaxis_title="Temperatura (°C)",
        hovermode="x unified"
    )

    st.plotly_chart(
        fig_temp,
        use_container_width=True
    )

    # ---------------------------
    # GRÁFICA DE HUMEDAD
    # ---------------------------
    st.subheader("💧 Humedad por intervalo")

    fig_hum = px.bar(
        df_grafica,
        x="_time",
        y="humidity",
        title=f"Humedad promedio — {resolucion}",
        labels={
            "_time": "Fecha y hora",
            "humidity": "Humedad (%)"
        },
        color_discrete_sequence=["#00CC96"]
    )

    fig_hum.update_layout(
        xaxis_title="Fecha y hora",
        yaxis_title="Humedad (%)",
        hovermode="x unified"
    )

    st.plotly_chart(
        fig_hum,
        use_container_width=True
    )

    # ---------------------------
    # TABLA DE PROMEDIOS
    # ---------------------------
    st.subheader("⏱️ Datos agrupados")

    df_tabla = df_grafica.copy()
    df_tabla["_time"] = (
        df_tabla["_time"]
        .dt.strftime("%Y-%m-%d %H:%M UTC")
    )

    st.dataframe(
        df_tabla.rename(columns={
            "_time": "Fecha y hora",
            "temperature": "Temperatura (°C)",
            "humidity": "Humedad (%)"
        }),
        use_container_width=True,
        hide_index=True
    )

    # ---------------------------
    # DATOS CRUDOS
    # ---------------------------
    with st.expander("📋 Ver datos crudos"):
        st.dataframe(
            df.sort_values("_time", ascending=False).head(500),
            use_container_width=True,
            hide_index=True
        )

else:
    st.warning(
        "No hay datos disponibles para el intervalo seleccionado."
    )

# ---------------------------
# AUTO REFRESH
# ---------------------------
if refresh > 0:
    import time
    time.sleep(refresh)
    st.rerun()
