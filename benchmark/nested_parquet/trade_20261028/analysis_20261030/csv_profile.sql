.timer on
CREATE MACRO n(s) AS CASE WHEN length(s)<=2 THEN 0 ELSE length(s)-length(replace(s,',',''))+1 END;
CREATE MACRO prof(f) AS TABLE
SELECT count(*) nrows, count(DISTINCT column00) n_asof, min(column00) d_min, max(column00) d_max,
  count(DISTINCT column03) n_trade, count(DISTINCT column01) n_c1, list(DISTINCT column01) c1_vals, count(DISTINCT (column00,column01,column03)) n_key, list(DISTINCT column08) c8_vals, list(DISTINCT column07) c7_vals, count(DISTINCT column19) n_c19,
  avg(n(column11)) l11, max(n(column11)) mx11, avg(n(column12)) l12, avg(n(column13)) l13,
  avg(n(column14)) l14, avg(n(column15)) l15, max(n(column15)) mx15, avg(n(column16)) l16, avg(n(column17)) l17, avg(n(column18)) l18,
  sum(CASE WHEN n(column15)=n(column16) AND n(column16)=n(column17) AND n(column17)=n(column18) THEN 1 ELSE 0 END) legs_aligned
FROM read_csv(f, header=false, all_varchar=true);
