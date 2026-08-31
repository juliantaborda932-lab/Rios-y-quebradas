import requests
import pandas as pd
import numpy as np
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ------------------------------------------------------------------
# Parámetros Fijos de la Estación y Estudiante
# ------------------------------------------------------------------
NOMBRE_ESTUDIANTE = "Julian Taborda Bedoya"
CODIGO_ESTACION = "34"
NOMBRE_ESTACION = "Quebrada La Grande (La Ceja)"
LAT_ESTACION = 6.0254
LON_ESTACION = -75.4337

API_BASE_URL = "https://marco.cornare.gov.co/api/v1/estaciones"
LLAVE_FECHA = "level_date"
LLAVE_VALOR = "level"

st.set_page_config(
    page_title=f"Estación {CODIGO_ESTACION} — {NOMBRE_ESTUDIANTE}",
    page_icon="🌊",
    layout="wide"
)

# ------------------------------------------------------------------
# Funciones de Consulta y Procesamiento
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
# Sidebar — Controles de Fecha Exclusivos
# ------------------------------------------------------------------
st.sidebar.header("⚙️ Rango de Fechas")
fecha_desde = st.sidebar.date_input("Desde", pd.to_datetime("2026-08-23")).strftime("%Y-%m-%d")
fecha_hasta = st.sidebar.date_input("Hasta", pd.to_datetime("2026-08-30")).strftime("%Y-%m-%d")
calidad = st.sidebar.selectbox("Filtro de Calidad", [1, 0], index=0, help="1 = solo datos validados")

consultar = st.sidebar.button("🔍 Consultar Estación 34", type="primary")

# ------------------------------------------------------------------
# Encabezado Principal Personalizado
# ------------------------------------------------------------------
st.title(f"🌊 Monitoreo Hidrológico — {NOMBRE_ESTACION}")
st.caption(f"Estudiante: **{NOMBRE_ESTUDIANTE}** · Estación activa: **{CODIGO_ESTACION}**")

# ------------------------------------------------------------------
# Consulta y Procesamiento de la Estación 34
# ------------------------------------------------------------------
if consultar:
    with st.spinner(f"Consultando datos para la Estación {CODIGO_ESTACION}..."):
        datos_crudos, error = obtener_serie_nivel(CODIGO_ESTACION, fecha_desde, fecha_hasta, calidad)

    if error:
        st.error(f"❌ {error}")
    else:
        registros = obtener_todas_las_paginas(datos_crudos)

        if not registros:
            st.warning("No hay registros para la Estación 34 en este rango de fechas. Prueba con otras fechas.")
        else:
            # 1. Preparación de datos crudos
            df = pd.DataFrame(registros)
            df = df.rename(columns={LLAVE_FECHA: "fecha", LLAVE_VALOR: "nivel"})
            df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
            df["nivel"] = pd.to_numeric(df["nivel"], errors="coerce")
            df = df.dropna(subset=["fecha", "nivel"]).sort_values("fecha").reset_index(drop=True)

            indice_calidad, huecos, n_outliers = calcular_indice_calidad(df)

            # 2. Filtrado IQR para métricas reales
            Q1, Q3 = df["nivel"].quantile(0.25), df["nivel"].quantile(0.75)
            IQR = Q3 - Q1
            lim_inf, lim_sup = Q1 - 1.5 * IQR, Q3 + 1.5 * IQR
            
            df_limpio = df[(df["nivel"] >= lim_inf) & (df["nivel"] <= lim_sup) & (df["nivel"] >= 0)].copy()
            if df_limpio.empty:
                df_limpio = df.copy()

            # 3. Cálculos de la estación sobre datos filtrados
            df_limpio["diferencia_horas"] = df_limpio["fecha"].diff().dt.total_seconds() / 3600.0
            df_limpio["tasa_cambio_m_h"] = (df_limpio["nivel"].diff() / df_limpio["diferencia_horas"]).replace([np.inf, -np.inf], np.nan)

            media_nivel = df_limpio["nivel"].mean()
            std_nivel = df_limpio["nivel"].std()
            max_nivel = df_limpio["nivel"].max()
            min_nivel = df_limpio["nivel"].min()
            max_tasa_subida = df_limpio["tasa_cambio_m_h"].max()

            # Umbrales fijos para la Estación 34
            umbral_amarillo = 25.0
            umbral_rojo = 30.0

            # ------------------------------------------------------
            # UI: Muestreo de Resultados
            # ------------------------------------------------------

            # --- 1. Semáforo de Alerta ---
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

            # --- 2. Métricas del Sensor ---
            st.subheader("📋 Resumen General del Sensor (Estación 34)")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Lecturas Totales", len(df))
            col2.metric("Nivel Promedio", f"{media_nivel:.2f} m")
            col3.metric("Índice de Calidad", f"{indice_calidad} / 100")
            col4.metric("Outliers Detectados", n_outliers)

            # --- 3. Hidrograma ---
            st.subheader("📈 Hidrograma: Serie de Nivel")
            st.caption("Visualización del nivel registrado directamente por el sensor.")
            st.line_chart(df.set_index("fecha")["nivel"])

            # --- 4. Ubicación de la Estación 34 ---
            st.subheader("📍 Ubicación de la Estación")
            st.caption(f"📍 Coordenadas de la Estación 34 — {NOMBRE_ESTACION} ({LAT_ESTACION}, {LON_ESTACION})")
            st.map(pd.DataFrame({"lat": [LAT_ESTACION], "lon": [LON_ESTACION]}), zoom=14)

            # --- 5. Desplegables de Análisis ---
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
                    st.write(f"- Rango de variación ($\Delta_{{máx-mín}}$): **{max_nivel - min_nivel:.2f} m**")
                    st.write(f"- Mediana ($P_{{50}}$): **{df_limpio['nivel'].median():.2f} m**")
                    st.write(f"- Umbral Alerta Amarilla: **{umbral_amarillo:.2f} m**")
                    st.write(f"- Umbral Alerta Roja: **{umbral_rojo:.2f} m**")

            with st.expander("🔍 Auditoría de Calidad"):
                st.write(f"- Huecos de reporte en serie temporal: **{huecos}**")
                st.write(f"- Lecturas fuera de rango (Outliers IQR): **{n_outliers}** de {len(df)}")

            with st.expander("💾 Visualizar y descargar datos"):
                st.dataframe(df_limpio[["fecha", "nivel", "tasa_cambio_m_h"]], use_container_width=True)
                csv = df_limpio.to_csv(index=False).encode("utf-8")
                st.download_button("⬇️ Descargar CSV Estación 34", csv, file_name=f"reporte_estacion_34_{fecha_desde}_a_{fecha_hasta}.csv", mime="text/csv")

else:
    st.info("Selecciona el rango de fechas en la barra lateral y pulsa **Consultar Estación 34**.")
