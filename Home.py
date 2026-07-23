# -*- coding: utf-8 -*-
"""
메인 진입점. Streamlit Cloud 배포 시 "Main file path"를 이 파일로 지정하세요.

st.navigation을 사용해 사이드바 표시 이름(한글)과 실제 파일 경로(영문)를
분리했습니다. 파일명을 영문으로 유지하면 zip 압축/해제, git clone 과정에서
한글 파일명이 깨지는(mojibake) 문제를 원천적으로 피할 수 있습니다.
"""
import streamlit as st

st.set_page_config(
    page_title="검진기관 찾기",
    page_icon="🏥",
    layout="wide",
)

home_page = st.Page("views/home.py", title="홈", icon="🏠", default=True)
hmc_page = st.Page("views/hmc_finder.py", title="검진기관 찾기", icon="🏥")

pg = st.navigation([home_page, hmc_page])
pg.run()
