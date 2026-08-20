from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
import urllib3


urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


SITIOS = {
    "CEPROBOL": [
        "https://www.ceprobol.gob.bo/",
        "https://ceprobol.gob.bo/",
        "http://www.ceprobol.gob.bo/",
        "http://ceprobol.gob.bo/",
    ],
    "FUNDEMPRESA": [
        "https://www.fundempresa.org.bo/",
        "https://fundempresa.org.bo/",
        "http://www.fundempresa.org.bo/",
        "http://fundempresa.org.bo/",
    ],
    "MEFP": [
        "https://www.economiayfinanzas.gob.bo/",
        "https://economiayfinanzas.gob.bo/",
        "http://www.economiayfinanzas.gob.bo/",
        "http://economiayfinanzas.gob.bo/",
    ],
    "MHE": [
        "https://www.hidrocarburos.gob.bo/",
        "https://hidrocarburos.gob.bo/",
        "http://www.hidrocarburos.gob.bo/",
        "http://hidrocarburos.gob.bo/",
    ],
    "SABSA": [
        "https://www.sabsa.aero/",
        "https://sabsa.aero/",
        "http://www.sabsa.aero/",
        "http://sabsa.aero/",
    ],
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


def probar_robots(session: requests.Session, url: str) -> str:
    parsed = urlparse(url)

    robots_url = (
        f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    )

    try:
        response = session.get(
            robots_url,
            timeout=6,
            allow_redirects=True,
            verify=False,
        )

        if response.status_code != 200:
            return f"robots HTTP {response.status_code}"

        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())

        if not parser.can_fetch("*", url):
            return "BLOQUEADO"

        return "PERMITIDO"

    except Exception as error:
        return f"NO COMPROBADO ({type(error).__name__})"


def probar_sitio(nombre: str, urls: list[str]) -> None:
    print()
    print("=" * 78)
    print(nombre)
    print("=" * 78)

    session = requests.Session()
    session.headers.update(HEADERS)

    hubo_respuesta = False

    for url in urls:
        try:
            response = session.get(
                url,
                timeout=8,
                allow_redirects=True,
                verify=False,
            )

            hubo_respuesta = True

            print(
                f"{url}"
                f" -> HTTP {response.status_code}"
                f" -> final={response.url}"
            )

            if response.status_code == 403:
                print("CLASIFICACIÓN POSIBLE: fuente denegada")
                return

            if response.status_code == 200:
                robots = probar_robots(
                    session,
                    response.url,
                )

                print(
                    f"robots.txt -> {robots}"
                )

                if robots == "BLOQUEADO":
                    print(
                        "CLASIFICACIÓN POSIBLE: "
                        "bloqueo por robot.txt"
                    )
                else:
                    print(
                        "CLASIFICACIÓN POSIBLE: "
                        "sin enlace directo"
                    )

                return

        except Exception as error:
            print(
                f"{url}"
                f" -> {type(error).__name__}: {error}"
            )

    if not hubo_respuesta:
        print(
            "SIN RESPUESTA HTTP: ninguna de las cuatro "
            "glosas describe técnicamente este caso."
        )


def main() -> None:
    for nombre, urls in SITIOS.items():
        probar_sitio(
            nombre,
            urls,
        )


if __name__ == "__main__":
    main()