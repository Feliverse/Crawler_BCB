from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from Crawler_BCB.Old_Files.crawler_multifuente.core.site_adapter import (
    CrawlSeed,
    SiteAdapter,
)


class AsfiAdapter(SiteAdapter):
    """
    Adapter estructural de ASFI.

    Su única responsabilidad específica es comprender el menú
    jerárquico del portal ASFI y convertirlo en seeds con rutas.

    La navegación, detección de archivos, ZIP y exportación
    continúan siendo responsabilidad del core.
    """

    def build_seeds(
        self,
        client,
    ) -> list[CrawlSeed]:

        try:
            response = client.get(
                self.config.base_url
            )

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            seeds = self._extract_menu(
                soup
            )

        except Exception:
            seeds = []

        # Fallback seguro: si ASFI modifica el menú,
        # seguimos pudiendo entrar por los entrypoints configurados.
        if not seeds:
            return super().build_seeds(
                client
            )

        existing_urls = {
            seed.url
            for seed in seeds
        }

        # Los entrypoints declarados siguen siendo válidos como
        # respaldo y como zonas prioritarias.
        for entrypoint in self.config.get_entrypoints():

            if entrypoint in existing_urls:
                continue

            seeds.append(
                CrawlSeed(
                    url=entrypoint,
                    path=(
                        "RAIZ",
                        self._label_from_url(
                            entrypoint
                        ),
                    ),
                )
            )

        return seeds

    def _extract_menu(
        self,
        soup: BeautifulSoup,
    ) -> list[CrawlSeed]:

        seeds: list[CrawlSeed] = []
        seen_urls: set[str] = set()

        main_items = soup.select(
            "ul.navbar-nav > li.nav-item.dropdown-center"
        )

        if not main_items:
            main_items = soup.select(
                "ul.navbar-nav > li.dropdown"
            )

        for macro_item in main_items:

            macro_element = (
                macro_item.find(
                    "a",
                    class_="texto-nivel-0",
                )
                or macro_item.find(
                    "span",
                    class_="texto-nivel-0",
                )
            )

            if not macro_element:
                continue

            macro_name = macro_element.get_text(
                " ",
                strip=True,
            )

            if not macro_name:
                continue

            dropdown = macro_item.find(
                "ul",
                class_="dropdown-menu",
            )

            if not dropdown:
                continue

            menu_container = dropdown.find(
                "div",
                class_="menu-principal",
            )

            if not menu_container:
                menu_container = dropdown

            categories = menu_container.find_all(
                "li",
                recursive=False,
            )

            for category_item in categories:

                category_element = (
                    category_item.find(
                        "a",
                        class_="texto-nivel-1",
                    )
                    or category_item.find(
                        "span",
                        class_="texto-nivel-1",
                    )
                )

                if not category_element:
                    continue

                category_name = (
                    category_element.get_text(
                        " ",
                        strip=True,
                    )
                )

                if not category_name:
                    continue

                sub_menu = category_item.find(
                    "ul",
                    class_="collapse",
                )

                if sub_menu:
                    for anchor in sub_menu.find_all(
                        "a",
                        href=True,
                    ):
                        href = str(
                            anchor.get(
                                "href",
                                "",
                            )
                        ).strip()

                        sub_name = anchor.get_text(
                            " ",
                            strip=True,
                        )

                        if (
                            not href
                            or href.startswith("#")
                            or not sub_name
                        ):
                            continue

                        absolute = urljoin(
                            self.config.base_url,
                            href,
                        )

                        if not self.config.domain_is_allowed(
                            absolute
                        ):
                            continue

                        if absolute in seen_urls:
                            continue

                        seen_urls.add(
                            absolute
                        )

                        seeds.append(
                            CrawlSeed(
                                url=absolute,
                                path=(
                                    macro_name,
                                    category_name,
                                    sub_name,
                                ),
                            )
                        )

                    continue

                href = category_element.get(
                    "href"
                )

                if not href:
                    continue

                href = str(
                    href
                ).strip()

                if (
                    not href
                    or href.startswith("#")
                ):
                    continue

                absolute = urljoin(
                    self.config.base_url,
                    href,
                )

                if not self.config.domain_is_allowed(
                    absolute
                ):
                    continue

                if absolute in seen_urls:
                    continue

                seen_urls.add(
                    absolute
                )

                seeds.append(
                    CrawlSeed(
                        url=absolute,
                        path=(
                            macro_name,
                            category_name,
                        ),
                    )
                )

        return seeds