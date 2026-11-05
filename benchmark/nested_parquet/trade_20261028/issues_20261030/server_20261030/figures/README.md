# 발표용 그래프 데이터

`make_figures.py`가 만듭니다. 시간은 1스레드, 1억 행(TPC-H는 표시한 SF)입니다.

| 파일 | 행 | 출처 (`server_20261030/` 기준) |
|---|---|---|
| `fig1_category_shares.csv` | 696 | issue1/profile/{params,tpch_sf1,tpch_sf10}/*.folded.gz, issue1c/profile/params/*.folded.gz (categories.py로 다시 분류) |
| `fig2_stage_vs_perf.csv` | 150 | issue1/stage_time.csv (RUNS=10 중 최소), issue1/profile/stage/*.folded.gz |
| `fig3_qerror.csv` | 379 | issue2/cardinality.csv (join과 UNNEST 행만) |
| `fig4_q7_variants.csv` | 30 | issue2/variants.csv |
| `fig5_fanout.csv` | 110 | extra2/fanout.csv (후속 D) |
| `fig6_overhead_composition.csv` | 120 | issue1/profile/params (q1_s01, q1_s50), issue1c/profile/params (q6_group, q7_csa, q7_plots), 새 기준 perf 범주; B의 join은 perf join 범주 전체(차원 표 join 포함) |
