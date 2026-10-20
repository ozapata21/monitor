import os

import httpx
import pandas as pd
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="NOC Python Monitor", layout="wide")


def api_get(path: str, **params):
    headers = {"Authorization": f"Bearer {st.session_state['token']}"}
    r = httpx.get(f"{API_URL}{path}", headers=headers, params=params, timeout=10)
    if r.status_code == 401:
        st.session_state.pop("token", None)
        st.rerun()
    r.raise_for_status()
    return r.json()


def login_view() -> None:
    st.title("NOC Python Monitor")
    with st.form("login"):
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar"):
            try:
                r = httpx.post(
                    f"{API_URL}/auth/login",
                    data={"username": username, "password": password},
                    timeout=10,
                )
            except httpx.HTTPError:
                st.error("No se pudo contactar la API")
                return
            if r.status_code == 200:
                st.session_state["token"] = r.json()["access_token"]
                st.rerun()
            st.error("Usuario o contraseña incorrectos")


@st.fragment(run_every=30)
def dashboard_view() -> None:
    devices = api_get("/devices", limit=500)
    df = pd.DataFrame(devices)

    st.subheader("Estado general")
    counts = df["status"].value_counts() if not df.empty else pd.Series(dtype=int)
    cols = st.columns(4)
    for col, status in zip(cols, ["UP", "DEGRADED", "DOWN", "UNKNOWN"]):
        col.metric(status, int(counts.get(status, 0)))

    st.subheader("Dispositivos")
    if df.empty:
        st.info("No hay dispositivos registrados")
    else:
        site = st.selectbox("Sitio", ["Todos"] + sorted(df["site_id"].unique()))
        view = df if site == "Todos" else df[df["site_id"] == site]
        st.dataframe(
            view[["hostname", "ip_address", "device_type", "site_id", "status", "updated_at"]],
            use_container_width=True, hide_index=True,
        )

        st.subheader("Métricas")
        name = st.selectbox("Dispositivo", view["hostname"].tolist())
        device_id = view.loc[view["hostname"] == name, "id"].iloc[0]
        metric_type = st.selectbox("Métrica", ["ICMP_RTT", "ICMP_LOSS", "RTSP", "SNMP_UPTIME"])
        metrics = pd.DataFrame(api_get(f"/devices/{device_id}/metrics", metric_type=metric_type))
        if metrics.empty:
            st.caption("Sin datos todavía")
        else:
            metrics["timestamp"] = pd.to_datetime(metrics["timestamp"])
            st.line_chart(metrics.set_index("timestamp")["value"])

    st.subheader("Alertas recientes")
    alerts = pd.DataFrame(api_get("/alerts", limit=50))
    if alerts.empty:
        st.caption("Sin alertas")
    else:
        names = {d["id"]: d["hostname"] for d in devices}
        alerts["hostname"] = alerts["device_id"].map(names)
        st.dataframe(
            alerts[["timestamp", "hostname", "kind", "message"]],
            use_container_width=True, hide_index=True,
        )


if "token" not in st.session_state:
    login_view()
else:
    st.title("NOC Python Monitor")
    if st.sidebar.button("Cerrar sesión"):
        st.session_state.pop("token")
        st.rerun()
    dashboard_view()
