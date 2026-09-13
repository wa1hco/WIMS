# Decision: 222/432 IF radios + N1MM kHz / microwave bands

**Status:** adopted 2026-09-12  
**Context:** ARRL VHF fleet. N1MM Network Status on this LAN shows **Band 10000**,
**Freq 10368090.00** for **MGEF-10-UP** (10 GHz / 3cm at 10368.090 MHz). That is
N1MM’s native kHz Freq + MHz Band, not a misread of 432. Separately, **MGEF-432**
uses a transverter on a **28 MHz** radio and **MGEF-222** uses a **21 MHz** radio;
RadioInfo / WSJT-X Status may report IF when the transverter offset is off.

## Facts (from DXLOG + Network Status)

| Host | N1MM Band (MHz) | DXLOG Freq (kHz) | RF |
|------|----------------:|-----------------:|----|
| MGEF-222 | 222 | 222090–222176 | 222 MHz |
| MGEF-432 | 420 | 432090–446000 | 432 MHz |
| MGEF-10-UP | **10000** | **10368090.00** | **10368.090 MHz (3cm)** |

N1MM **RadioInfo `<Freq>`** is 10 Hz units (14417400 → 144.174 MHz). **Network
Status / DXLOG Freq** is kHz. WIMS must accept both (`n1mm_raw_to_hz`).

## Rules

1. **Microwave bands** in `band_label`: 13cm / 9cm / 6cm / 3cm / 1.2cm so
   `band_label_mhz(10000)` is **3cm**, not 13cm (old last bucket).
2. **IF → RF** (default on; `WIMS_TRANSVERTER=0` disables):
   - 21.000–24.000 MHz → +201 MHz (**222**)
   - 28.000–29.700 MHz → +404 MHz (**432**)
   Already-RF dial (222 / 432 / 10368) is unchanged. 10 GHz on MGEF-10-UP is RF
   in N1MM, so it is not mapped through the 28 MHz IF window.
3. Log ADIF with IF FREQ/BAND is rewritten to RF before N1MM ingest.

## Not this

Do not treat Network Status 10368090 as 28 MHz×something or as 432. It is 10 GHz.
