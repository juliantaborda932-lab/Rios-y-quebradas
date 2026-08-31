import requests
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import urllib3

# Desactivar advertencias de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ------------------------------------------------------------------
# 1. Configuración de Página y CSS Personalizado
# ------------------------------------------------------------------
st.set_page_config(
    page_title="Estación 34 — Julian Taborda Bedoya",
    page_icon="🌊",
    layout="wide"
)

st.markdown("""
<style>
    .stApp { background-color: #F8FAFC; }
    
    .titulo-principal {
        color: #0F172A !important;
        font-family: 'Segoe UI', Roboto, sans-serif;
        font-weight: 800;
        font-size: 2.2rem;
        line-height: 1.2;
        margin-bottom: 0.2rem;
    }
    .subtitulo-grande {
        color: #1E293B !important;
        font-family: 'Segoe UI', Roboto, sans-serif;
        font-weight: 800;
        font-size: 1.8rem;
        line-height: 1.2;
        margin-top: 0;
        margin-bottom: 1.5rem;
    }

    div.stButton > button:first-child {
        background: linear-gradient(135deg, #0284C7 0%, #0369A1 100%);
        color: #FFFFFF !important;
        border: none;
        border-radius: 8px;
        font-weight: 700;
        font-size: 1rem;
        padding: 0.6rem 1rem;
        margin-top: 25px;
    }

    .cauce-card {
        background-color: #FFFFFF;
        padding: 24px;
        border-radius: 16px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 4px 12px rgba(0,0,0,0.04);
        margin-bottom: 25px;
    }

    [data-testid="stMetric"] {
        background-color: #FFFFFF;
        padding: 16px 20px;
        border-radius: 12px;
        border-left: 5px solid #0284C7;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    
    .alert-card-verde {
        background-color: #ECFDF5;
        border: 2px solid #10B981;
        border-radius: 12px;
        padding: 14px;
        color: #065F46;
        text-align: center;
    }
    .alert-card-amarilla {
        background-color: #FFFBEB;
        border: 2px solid #F59E0B;
        border-radius: 12px;
        padding: 14px;
        color: #92400E;
        text-align: center;
    }
    .alert-card-roja {
        background-color: #FEF2F2;
        border: 2px solid #EF4444;
        border-radius: 12px;
        padding: 14px;
        color: #991B1B;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------
# 2. Parámetros Fijos y Session State
# ------------------------------------------------------------------
NOMBRE_ESTUDIANTE = "Julian Taborda Bedoya"
CODIGO_ESTACION = "34"
NOMBRE_ESTACION = "Quebrada La Grande (La Ceja)"
LAT_ESTACION = 6.0254
LON_ESTACION = -75.4337
API_BASE_URL = "https://marco.cornare.gov.co/api/v1/estaciones"

UMBRAL_VERDE = 72.0      # cm
UMBRAL_AMARILLO = 107.0  # cm

# Inicializar estado persistente para los datos
if "df_datos" not in st.session_state:
    st.session_state.df_datos = None

# ------------------------------------------------------------------
# 3. Funciones de Consulta y Cálculo
# ------------------------------------------------------------------
def obtener_serie_nivel(codigo_estacion, desde, hasta, calidad=1):
    url = f"{API_BASE_URL}/{codigo_estacion}/nivel"
    params = {"desde": desde, "hasta": hasta, "calidad": calidad}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30, verify=False)
        return (resp.json(), None) if resp.status_code == 200 else (None, f"HTTP {resp.status_code}")
    except Exception as e:
        return None, str(e)

def obtener_todas_las_paginas(datos_json):
    registros = list(datos_json.get("values", []))
    siguiente_url = datos_json.get("next")
    while siguiente_url:
        try:
            resp = requests.get(siguiente_url, timeout=30, verify=False)
            if resp.status_code != 200: 
                break
            pagina = resp.json()
            registros.extend(pagina.get("values", []))
            siguiente_url = pagina.get("next")
        except Exception:
            break
    return registros

def calcular_indice_calidad(df):
    if df.empty or len(df) < 2:
        return 0.0, 0, 0

    diffs = df["fecha"].diff().dropna()
    if diffs.empty:
        return 0.0, 0, 0

    frecuencia_tipica = diffs.mode()
    freq = frecuencia_tipica.iloc[0] if len(frecuencia_tipica) > 0 else pd.Timedelta(minutes=5)
    
    rango_completo = pd.date_range(start=df["fecha"].min(), end=df["fecha"].max(), freq=freq)
    esperados = len(rango_completo)
    huecos = max(0, esperados - len(df))
    completitud = max(0.0, 1.0 - (huecos / esperados)) if esperados > 0 else 0.0

    Q1, Q3 = df["nivel_cm"].quantile(0.25), df["nivel_cm"].quantile(0.75)
    IQR = Q3 - Q1
    if IQR == 0:
        proporcion_outliers = 0.0
        n_outliers = 0
    else:
        lim_inf, lim_sup = Q1 - 1.5 * IQR, Q3 + 1.5 * IQR
        es_outlier = (df["nivel_cm"] < lim_inf) | (df["nivel_cm"] > lim_sup) | (df["nivel_cm"] < 0)
        proporcion_outliers = es_outlier.mean()
        n_outliers = int(es_outlier.sum())

    indice = (completitud * 0.7 + (1.0 - proporcion_outliers) * 0.3) * 100.0
    return round(indice, 1), int(huecos), n_outliers

# ------------------------------------------------------------------
# 4. Generador del Gráfico: Sección del Cauce (Fijo sin Zoom)
# ------------------------------------------------------------------
def generar_grafico_seccion_cauce(nivel_cm, umbral_verde=72, umbral_amarillo=107, y_max=368):
    nivel_cm = float(nivel_cm) if pd.notnull(nivel_cm) else 0.0

    x_base = np.array([0, 1.0, 1.6, 2.2, 5.3, 5.9, 6.5, 7.5])
    y_base = np.array([150, 150, 15, 0, 0, 15, 220, 220])
    
    x_fine = np.linspace(0, 7.5, 300)
    y_fine = np.interp(x_fine, x_base, y_base)

    fig = go.Figure()

    # Perfil del terreno
    fig.add_trace(go.Scatter(
        x=x_fine, y=y_fine,
        fill='tozeroy',
        fillcolor='#E5DEC9',
        line=dict(color='#D4CBB4', width=2),
        showlegend=False,
        hoverinfo='skip'
    ))

    # Nivel de agua
    if nivel_cm > 0:
        mask_agua = y_fine <= nivel_cm
        if np.any(mask_agua):
            x_water = x_fine[mask_agua]
            y_water_bot = y_fine[mask_agua]
            x_water_poly = np.concatenate([x_water, x_water[::-1]])
            y_water_poly = np.concatenate([y_water_bot, np.full_like(x_water, nivel_cm)])

            fig.add_trace(go.Scatter(
                x=x_water_poly, y=y_water_poly,
                fill='toself',
                fillcolor='rgba(125, 211, 252, 0.85)',
                line=dict(color='#38BDF8', width=1),
                showlegend=False,
                hoverinfo='skip'
            ))

    # Barra lateral de alertas
    fig.add_shape(type="rect", x0=7.6, y0=0, x1=8.1, y1=umbral_verde,
                  fillcolor="#10B981", line_width=0)
    fig.add_shape(type="rect", x0=7.6, y0=umbral_verde, x1=8.1, y1=umbral_amarillo,
                  fillcolor="#F59E0B", line_width=0)
    fig.add_shape(type="rect", x0=7.6, y0=umbral_amarillo, x1=8.1, y1=y_max,
                  fillcolor="#EF4444", line_width=0)

    # Línea horizontal del nivel de agua
    fig.add_shape(type="line", x0=0, y0=nivel_cm, x1=7.8, y1=nivel_cm,
                  line=dict(color="#0F172A", width=2, dash="dash"))

    # Anotación del nivel
    fig.add_annotation(
        x=7.8, y=nivel_cm,
        text=f"<b>{nivel_cm:.1f} cm ➔</b>",
        showarrow=False,
        font=dict(color="white", size=12),
        bgcolor="#0F172A",
        bordercolor="#0F172A",
        borderpad=5,
        xanchor="right"
    )

    # Bloqueo estricto de zoom y movimiento
    fig.update_layout(
        height=430,
        margin=dict(l=40, r=20, t=10, b=40),
        plot_bgcolor='white',
        paper_bgcolor='white',
        dragmode=False,
        xaxis=dict(
            title=dict(text="<b>Ancho cauce (m)</b>", font=dict(color="#64748B", size=12)),
            range=[-0.2, 8.3],
            showgrid=False,
            zeroline=False,
            dtick=2,
            fixedrange=True
        ),
        yaxis=dict(
            title=dict(text="<b>Nivel (cm)</b>", font=dict(color="#64748B", size=12)),
            range=[-5, y_max + 10],
            showgrid=True,
            gridcolor='#F1F5F9',
            zeroline=False,
            tickvals=[0, 100, 200, 300, 368],
            fixedrange=True
        )
    )
    return fig

# ------------------------------------------------------------------
# 5. Encabezado Principal
# ------------------------------------------------------------------
st.markdown(f'<div class="titulo-principal">🌊 Monitoreo Hidrológico — {NOMBRE_ESTACION}</div>', unsafe_allow_html=True)
st.markdown(f'<div class="subtitulo-grande">Estudiante: {NOMBRE_ESTUDIANTE} · Estación activa: {CODIGO_ESTACION}</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------
# 6. Panel Superior de Selección de Fechas
# ------------------------------------------------------------------
with st.container():
    col_f1, col_f2, col_f3, col_f4 = st.columns([3, 3, 3, 3])
    with col_f1:
        fecha_desde = st.date_input("Fecha Desde", pd.to_datetime("2026-08-29")).strftime("%Y-%m-%d")
    with col_f2:
        fecha_hasta = st.date_input("Fecha Hasta", pd.to_datetime("2026-08-30")).strftime("%Y-%m-%d")
    with col_f3:
        calidad = st.selectbox("Filtro de Calidad", [1, 0], index=0)
    with col_f4:
        consultar = st.button("🔍 Consultar Estación 34", type="primary", use_container_width=True)

st.markdown("<hr style='margin-top: 10px; margin-bottom: 25px; border: 0; border-top: 1px solid #E2E8F0;'>", unsafe_allow_html=True)

# ------------------------------------------------------------------
# 7. Procesamiento y Guardado en Estado
# ------------------------------------------------------------------
if consultar:
    with st.spinner("Cargando datos hidrológicos de la Estación 34..."):
        datos_crudos, error = obtener_serie_nivel(CODIGO_ESTACION, fecha_desde, fecha_hasta, calidad)

    if error:
        st.error(f"❌ {error}")
        st.session_state.df_datos = None
    else:
        registros = obtener_todas_las_paginas(datos_crudos)

        if not registros:
            st.warning("No se encontraron registros para el rango de fechas seleccionado.")
            st.session_state.df_datos = None
        else:
            df = pd.DataFrame(registros)
            df = df.rename(columns={"level_date": "fecha", "level": "nivel"})
            df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
            df["nivel"] = pd.to_numeric(df["nivel"], errors="coerce")
            df = df.dropna(subset=["fecha", "nivel"]).sort_values("fecha").reset_index(drop=True)

            es_en_metros = (df["nivel"].max() < 10.0) if not df.empty else False
            df["nivel_cm"] = df["nivel"] * 100.0 if es_en_metros else df["nivel"]

            df["diferencia_horas"] = df["fecha"].diff().dt.total_seconds() / 3600.0
            df["tasa_cambio_m_h"] = (df["nivel"].diff() / df["diferencia_horas"]).replace([np.inf, -np.inf], np.nan)

            # Persistir los datos procesados en la sesión
            st.session_state.df_datos = df

# ------------------------------------------------------------------
# 8. Renderizado Persistente
# ------------------------------------------------------------------
if st.session_state.df_datos is not None:
    df = st.session_state.df_datos

    max_nivel_cm = df["nivel_cm"].max()
    min_nivel_cm = df["nivel_cm"].min()
    media_nivel_cm = df["nivel_cm"].mean()
    std_nivel_cm = df["nivel_cm"].std()
    max_tasa_subida = df["tasa_cambio_m_h"].max()
    indice_calidad, huecos, n_outliers = calcular_indice_calidad(df)

    # --- SECCIÓN DEL CAUCE ---
    st.markdown('<div class="cauce-card">', unsafe_allow_html=True)
    
    c_head1, c_head2 = st.columns([6, 4])
    with c_head1:
        st.markdown('<div style="color:#0284C7; font-size:1.6rem; font-weight:800;">SECCIÓN DEL CAUCE</div>', unsafe_allow_html=True)
    with c_head2:
        modo_vista = st.radio(
            "Selección Nivel",
            options=["🌊 NIVEL ACTUAL", "🔝 MÁXIMO DEL PERÍODO"],
            horizontal=True,
            label_visibility="collapsed",
            key="modo_cauce_radio"
        )

    if modo_vista == "🌊 NIVEL ACTUAL":
        registro_sel = df.iloc[-1]
    else:
        registro_sel = df.loc[df["nivel_cm"].idxmax()]

    valor_cm = registro_sel["nivel_cm"]
    fecha_str = registro_sel["fecha"].strftime("%d/%m/%Y %H:%M Hr")

    st.markdown(f'<div style="text-align:center; font-weight:700; color:#0F172A; font-size:1.05rem;">Registrado el: {fecha_str}</div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="text-align:center; font-size:0.9rem; margin-top:6px; margin-bottom:12px;">
        <span style="font-weight:bold; color:#0F172A;">-- Nivel</span> &nbsp;&nbsp;&nbsp;
        <span style="color:#10B981; font-weight:bold;">🟢 Seguro (&lt; 72 cm)</span> &nbsp;&nbsp;&nbsp;
        <span style="color:#F59E0B; font-weight:bold;">🟡 Amarilla (72 - 107 cm)</span> &nbsp;&nbsp;&nbsp;
        <span style="color:#EF4444; font-weight:bold;">🔴 Roja (&ge; 107 cm)</span>
    </div>
    """, unsafe_allow_html=True)

    fig_cauce = generar_grafico_seccion_cauce(valor_cm, umbral_verde=UMBRAL_VERDE, umbral_amarillo=UMBRAL_AMARILLO, y_max=368)
    
    # Deshabilitar barra de herramientas e interactividad de zoom
    st.plotly_chart(
        fig_cauce,
        use_container_width=True,
        config={'displayModeBar': False, 'scrollZoom': False}
    )
    
    st.markdown('</div>', unsafe_allow_html=True)

    # --- SEMÁFORO Y MÉTRICAS ---
    st.subheader("🚨 Estado de Alerta por Nivel")
    col_a1, col_a2, col_a3, col_a4 = st.columns(4)

    with col_a1:
        if max_nivel_cm >= UMBRAL_AMARILLO:
            st.markdown(f'<div class="alert-card-roja"><h3 style="margin:0;">🔴 ALERTA ROJA</h3><p style="margin:0; font-size:1.1rem; font-weight:700;">Nivel máx: {max_nivel_cm:.1f} cm</p></div>', unsafe_allow_html=True)
        elif max_nivel_cm >= UMBRAL_VERDE:
            st.markdown(f'<div class="alert-card-amarilla"><h3 style="margin:0;">🟡 ALERTA AMARILLA</h3><p style="margin:0; font-size:1.1rem; font-weight:700;">Nivel máx: {max_nivel_cm:.1f} cm</p></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="alert-card-verde"><h3 style="margin:0;">🟢 NIVEL NORMAL</h3><p style="margin:0; font-size:1.1rem; font-weight:700;">Nivel máx: {max_nivel_cm:.1f} cm</p></div>', unsafe_allow_html=True)

    col_a2.metric("Máxima Creciente / Hora", f"{max_tasa_subida:.2f} m/h" if pd.notnull(max_tasa_subida) else "N/A")
    col_a3.metric("Nivel Mínimo Registrado", f"{min_nivel_cm:.1f} cm")
    col_a4.metric("Desviación Estándar (σ)", f"{std_nivel_cm:.2f}")

    st.markdown("<br>", unsafe_allow_html=True)

    # --- RESUMEN Y GRÁFICAS ---
    st.subheader("📋 Resumen General del Sensor (Estación 34)")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Lecturas Totales", len(df))
    col2.metric("Nivel Promedio", f"{media_nivel_cm:.1f} cm")
    col3.metric("Índice de Calidad", f"{indice_calidad} / 100")
    col4.metric("Outliers Detectados", n_outliers)

    st.markdown("<br>", unsafe_allow_html=True)

    st.subheader("📈 Hidrograma: Serie de Nivel (cm)")
    st.line_chart(df.set_index("fecha")["nivel_cm"], color="#0284C7")

    st.subheader("📍 Ubicación de la Estación")
    st.map(pd.DataFrame({"lat": [LAT_ESTACION], "lon": [LON_ESTACION]}), zoom=14)

else:
    st.info("Ajusta el rango de fechas en el panel superior y haz clic en **Consultar Estación 34**.")
