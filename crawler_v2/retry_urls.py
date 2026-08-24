from concurrent.futures import ThreadPoolExecutor, as_completed

from Crawler_BCB.crawler_v2.batch_full_crawl_all_live import crawl_one


FUENTES = [
    {
        "fila_excel": 0,
        "fuente": "CADEXCO",
        "institucion": "Cámara de Exportadores de Cochabamba",
        "url": "https://cadexco.bo/",
        "crawler_asignado": "",
    },
    {
        "fila_excel": 0,
        "fuente": "CEPAL",
        "institucion": "Comisión Económica para América Latina y el Caribe",
        "url": "https://www.cepal.org/es",
        "crawler_asignado": "",
    },
    {
        "fila_excel": 0,
        "fuente": "FAM",
        "institucion": "Federación de Asociaciones Municipales de Bolivia",
        "url": "https://fam.org.bo/",
        "crawler_asignado": "",
    },
    {
        "fila_excel": 0,
        "fuente": "FEGASACRUZ",
        "institucion": "Federación de Ganaderos de Santa Cruz",
        "url": "http://www.fegasacruz.org/",
        "crawler_asignado": "",
    },
    {
        "fila_excel": 0,
        "fuente": "FINRURAL/indicadores",
        "institucion": "Finrural Bolivia",
        "url": "https://www.finrural.org.bo/",
        "crawler_asignado": "",
    },
    {
        "fila_excel": 0,
        "fuente": "IBCH",
        "institucion": "Instituto Boliviano del Cemento y Hormigón",
        "url": "https://www.ibch.com/",
        "crawler_asignado": "",
    },
    {
        "fila_excel": 0,
        "fuente": "VIPFE",
        "institucion": "Viceministerio de Inversión Pública y Financiamiento Externo",
        "url": "https://www.planificacion.gob.bo/",
        "crawler_asignado": "",
    },
]


def main():
    print("=" * 80)
    print("REINTENTO DE URLS CORREGIDAS")
    print("=" * 80)

    resultados = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futuros = {
            executor.submit(crawl_one, fuente): fuente
            for fuente in FUENTES
        }

        for futuro in as_completed(futuros):
            fuente = futuros[futuro]

            try:
                resultado = futuro.result()
            except Exception as error:
                print(
                    f"[ERROR] {fuente['fuente']} | {error}"
                )
                continue

            resultados.append(resultado)

            print(
                f"[{resultado['resultado']}] "
                f"{resultado['fuente']} | "
                f"HTTP={resultado['http']} | "
                f"paginas={resultado['paginas']} | "
                f"archivos={resultado['archivos']} | "
                f"datasets={resultado['datasets']} | "
                f"docs={resultado['documentos']} | "
                f"detalle={resultado['detalle']}"
            )

    print()
    print("=" * 80)
    print("RESULTADOS")
    print("=" * 80)

    resultados.sort(
        key=lambda item: item["fuente"]
    )

    for r in resultados:
        print(
            f"{r['fuente']} | "
            f"{r['resultado']} | "
            f"HTTP={r['http']} | "
            f"docs={r['documentos']}"
        )


if __name__ == "__main__":
    main()