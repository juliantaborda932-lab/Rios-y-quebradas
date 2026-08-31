import requests
import pandas as pd
import numpy as np
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ------------------------------------------------------------------
# Ubicación por defecto y mapeo local por código de estación
# ------------------------------------------------------------------
LAT_DEFECTO = 6.0254
LON_DEFECTO = -75.4337

COORDENADAS_ESTACIONES = {
    "34": (6.0254, -75.4337),  # La Ceja, Quebrada La Grande
    "42": (6.2766, -75.5901),  # Institución Universitaria Pascual Bravo
}

API_BASE_URL = "https://marco.cornare.gov.co/api/v1/estaciones"

LLAVE_FECHA = "level_date"
LLAVE_VALOR = "level"
CANDIDATOS_LAT = ["lat", "latitude", "latitud"]
CANDIDATOS_LON = ["lng", "lon", "longitude", "longitud"]

st.set_page_config(page_title="Nivel de estación — CORNARE", page_icon="🌊", layout="wide")


# ------------------------------------------------------------------
# Funciones de consulta y detección
# ------------------------------------------------------------------
def obtener_serie_nivel(codigo_estacion, desde, hasta, calidad=1, timeout=30):
    url = f"{API_BASE_URL}/{codigo_estacion}/nivel"
    params = {"desde": desde, "hasta": hasta, "calidad": calidad}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout, verify=False)
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"HTTP {resp.status_code}"
    except requests.exceptions.RequestException as e:
        return None, f"Error de red: {e}"


def obtener_todas_las_paginas(datos_json, timeout=30):
    registros = list(datos_json.get("values", []))
    siguiente_url = datos_json.get("next")
    while siguiente_url:
        try:
            resp = requests.get(siguiente_url, timeout=timeout, verify=False)
        except requests.exceptions.RequestException:
            break
        if resp.status_code != 200:
            break
        pagina = resp.json()
        registros.extend(pagina.get("values", []))
        siguiente_url = pagina.get("next")
    return registros


def detectar_coordenadas(datos_json, codigo_estacion=""):
    """Detección en API -> Mapeo Local -> Coordenadas por defecto."""
    if isinstance(datos_json, dict):
        lat = next((datos_json[k] for k in CANDIDATOS_LAT if k in datos_json), None)
        lon = next((datos_json[k] for k in CANDIDATOS_LON if k in datos_json), None)

        if lat is not None and lon is not None:
            try:
                return float(lat), float(lon), "API"
            except (TypeError, ValueError):
                pass

    if str(codigo_estacion) in COORDENADAS_ESTACIONES:
        lat_map, lon_map = COORDENADAS_ESTACIONES[str(codigo_estacion)]
        return lat_map, lon_map, "Mapeo local"

    return LAT_DEFECTO, LON_DEFECTO, "Por defecto"


def calcular_indice_calidad(df):
    """Índice simple (0-100) combinando completitud de la serie y proporción de outliers."""
    if df.empty or len(df) < 2:
        return 0.0, 0, 0

    df_idx = df.set_index("fecha")
    frecuencia_tipica = df["fecha"].diff().dropna().mode()
    if len(frecuencia_tipica) == 0:
        return 0.0, 0, 0
    frecuencia_tipica = frecuencia_tipica[0]

    rango_completo = pd.date_range(start=df_idx.index.min(), end=df_idx.index.max(), freq=frecuencia_tipica)
    esperados = len(rango_completo)
    huecos = esperados - len(df_idx)
    completitud = max(0.0, 1 - (huecos / esperados)) if esperados > 0 else 0.0

    Q1, Q3 = df["nivel"].quantile(0.25), df["nivel"].quantile(0.75)
    IQR = Q3 - Q1
    lim_inf, lim_sup = Q1 - 1.5 * IQR, Q3 + 1.5 * IQR
    es_outlier = (df["nivel"] < lim_inf) | (df["nivel"] > lim_sup) | (df["nivel"] < 0)
    proporcion_outliers = es_outlier.mean()

    indice = (completitud * 0.7 + (1 - proporcion_outliers) * 0.3) * 100
    return round(indice, 1), int(huecos), int(es_outlier.sum())


# ------------------------------------------------------------------
# Sidebar — Parámetros de consulta y opciones de análisis
# ------------------------------------------------------------------
st.sidebar.header("⚙️ Parámetros de consulta")
nombre_estudiante = st.sidebar.text_input("Nombre del estudiante", "Tu Nombre Aquí")
codigo_estacion = st.sidebar.text_input("Código de estación", "34")
fecha_desde = st.sidebar.date_input("Desde", pd.to_datetime("2026-08-23")).strftime("%Y-%m-%d")
fecha_hasta = st.sidebar.date_input("Hasta", pd.to_datetime("2026-08-30")).strftime("%Y-%m-%d")
calidad = st.sidebar.selectbox("Calidad", [1, 0], index=0, help="1 = solo datos validados")

st.sidebar.markdown("---")
st.sidebar.header("📊 Filtros de Visualización")
ventana_suavizado = st.sidebar.slider("Ventana de suavizado (Media Móvil)", min_value=1, max_value=24, value=5)

consultar = st.sidebar.button("🔍 Consultar", type="primary")

# ------------------------------------------------------------------
# Encabezado principal
# ------------------------------------------------------------------
st.title("🌊 Monitoreo Hidrológico de Ríos y Quebradas — CORNARE")
st.caption(f"Estudiante: **{nombre_estudiante}** · Estación activa: **{codigo_estacion}**")

# ------------------------------------------------------------------
# Consulta y Procesamiento Avanzado
# ------------------------------------------------------------------
if consultar:
    with st.spinner("Consultando la API de CORNARE..."):
        datos_crudos, error = obtener_serie_nivel(codigo_estacion, fecha_desde, fecha_hasta, calidad)

    if error:
        st.error(f"❌ {error}")
    else:
        registros = obtener_todas_las_paginas(datos_crudos)

        if not registros:
            st.warning("No hay registros para esta estación y rango de fechas. Prueba otro código u otro rango.")
        else:
            # 1. Limpieza y preparación de datos
            df = pd.DataFrame(registros)
            df = df.rename(columns={LLAVE_FECHA: "fecha", LLAVE_VALOR: "nivel"})
            df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
            df["nivel"] = pd.to_numeric(df["nivel"], errors="coerce")
            df = df.dropna(subset=["fecha", "nivel"]).sort_values("fecha").reset_index(drop=True)

            # 2. Cálculos hidrológicos avanzados
            lat, lon, origen_coords = detectar_coordenadas(datos_crudos, codigo_estacion)
            indice_calidad, huecos, n_outliers = calcular_indice_calidad(df)

            # Suavizado de media móvil
            df["nivel_suavizado"] = df["nivel"].rolling(window=ventana_suavizado, min_periods=1).mean()

            # Cálculo de la tasa de cambio / velocidad de crecimiento (m/h)
            df["diferencia_horas"] = df["fecha"].diff().dt.total_seconds() / 3600.0
            df["tasa_cambio_m_h"] = (df["nivel"].diff() / df["diferencia_horas"]).replace([np.inf, -np.inf], np.nan)

            # ------------------------------------------------------
            # Filtrado de Outliers para alertas y estadísticas reales
            # ------------------------------------------------------
            Q1, Q3 = df["nivel"].quantile(0.25), df["nivel"].quantile(0.75)
            IQR = Q3 - Q1
            lim_inf, lim_sup = Q1 - 1.5 * IQR, Q3 + 1.5 * IQR
            df_limpio = df[(df["nivel"] >= lim_inf) & (df["nivel"] <= lim_sup) & (df["nivel"] >= 0)]
            if df_limpio.empty:
                df_limpio = df

            # Métricas estadísticas para umbrales de alerta (calculadas sobre datos válidos sin errores)
            media_nivel = df_limpio["nivel"].mean()
            std_nivel = df_limpio["nivel"].std()
            max_nivel = df_limpio["nivel"].max()
            min_nivel = df_limpio["nivel"].min()
            max_tasa_subida = df_limpio["tasa_cambio_m_h"].max()

            umbral_amarillo = media_nivel + std_nivel
            umbral_rojo = media_nivel + (2 * std_nivel)

            # ------------------------------------------------------
            # UI: Muestreo de Resultados
            # ------------------------------------------------------

            # --- 1. Semáforo de Alerta Temprana ---
            st.subheader("🚨 Estado de Alerta por Nivel")
            col_a1, col_a2, col_a3, col_a4 = st.columns(4)

            if max_nivel >= umbral_rojo:
                col_a1.error(f"🔴 **ALERTA ROJA**\n\nNivel máx: **{max_nivel:.2f} m**")
            elif max_nivel >= umbral_amarillo:
                col_a1.warning(f"🟡 **ALERTA AMARILLA**\n\nNivel máx: **{max_nivel:.2f} m**")
            else:
                col_a1.success(f"🟢 **NIVEL NORMAL**\n\nNivel máx: **{max_nivel:.2f} m**")

            col_a2.metric("Máxima Creciente / Hora", f"{max_tasa_subida:.2f} m/h" if pd.notnull(max_tasa_subida) else "N/A")
            col_a3.metric("Nivel Mínimo Registrado", f"{min_nivel:.2f} m")
            col_a4.metric("Desviación Estándar ($\sigma$)", f"{std_nivel:.2f}")

            st.markdown("---")

            # --- 2. Métricas de Integridad del Sensor ---
            st.subheader("📋 Resumen General del Sensor")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Lecturas Totales", len(df))
            col2.metric("Nivel Promedio", f"{media_nivel:.2f} m")
            col3.metric("Índice de Calidad", f"{indice_calidad} / 100")
            col4.metric("Outliers Detectados", n_outliers)

            # --- 3. Gráfico Interactivo de Nivel ---
            st.subheader("📈 Hidrograma: Serie de Nivel y Tendencia")
            st.caption(f"Comparativa entre el nivel real registrado y el promedio móvil ajustado a **{ventana_suavizado}** muestras.")
            st.line_chart(df.set_index("fecha")[["nivel", "nivel_suavizado"]])

            # --- 4. Mapa de Ubicación Geográfica ---
            st.subheader("📍 Ubicación de la Estación")
            if origen_coords == "Mapeo local":
                st.caption(f"📍 Coordenadas mapeadas localmente para la estación **{codigo_estacion}** ({lat}, {lon}).")
            elif origen_coords == "Por defecto":
                st.caption(f"⚠️ Coordenadas genéricas por defecto ({lat}, {lon}).")
            else:
                st.caption(f"🌐 Coordenadas directo desde la API ({lat}, {lon}).")

            st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=13)

            # --- 5. Análisis Técnico Avanzado (Expanders) ---
            with st.expander("📊 Estadísticas hidrológicas y percentiles"):
                col_s1, col_s2 = st.columns(2)
                with col_s1:
                    st.write("**Percentiles de Distribución de Nivel**")
                    percentiles = df_limpio["nivel"].quantile([0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
                    df_p = pd.DataFrame({
                        "Percentil": [f"P{int(k*100)}" for k in percentiles.index],
                        "Nivel (m)": percentiles.values.round(3)
                    })
                    st.dataframe(df_p, use_container_width=True)

                with col_s2:
                    st.write("**Parámetros de Variabilidad**")
                    st.write(f"- Rango total de variación ($\Delta_{{máx-mín}}$): **{max_nivel - min_nivel:.2f} m**")
                    st.write(f"- Mediana ($P_{{50}}$): **{df_limpio['nivel'].median():.2f} m**")
                    st.write(f"- Umbral Alerta Amarilla ($\mu + 1\sigma$): **{umbral_amarillo:.2f} m**")
                    st.write(f"- Umbral Alerta Roja ($\mu + 2\sigma$): **{umbral_rojo:.2f} m**")

            with st.expander("🔍 Auditoría de Calidad y Huecos de Información"):
                st.write(f"- Huecos de reporte en serie temporal: **{huecos}**")
                st.write(f"- Lecturas fuera de rango (Outliers IQR / Nivel < 0): **{n_outliers}** de {len(df)}")
                st.write("El índice pondera la completitud del registro continuado (70%) junto a la baja tasa de anomalías (30%).")

            with st.expander("💾 Visualizar y descargar datos crudos"):
                st.dataframe(df[["fecha", "nivel", "nivel_suavizado", "tasa_cambio_m_h"]], use_container_width=True)
                csv = df.to_csv(index=False).encode("utf-8")
                st.download_button("⬇️ Descargar Reporte CSV", csv, file_name=f"reporte_estacion_{codigo_estacion}.csv", mime="text/csv")

else:
    st.info("Configura los parámetros en el panel lateral y pulsa el botón **Consultar**.")
