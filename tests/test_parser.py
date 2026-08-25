from crawler.parser import parse_table_rows


def test_parse_table_rows_simple():
    html = '''
    <html><body>
    <table>
      <tr><th>Moneda</th><th>Precio</th></tr>
      <tr><td>Oro</td><td>1000</td></tr>
      <tr><td>Plata</td><td>20</td></tr>
    </table>
    </body></html>
    '''
    rows = parse_table_rows(html)
    assert isinstance(rows, list)
    assert len(rows) == 2
    assert rows[0]["Moneda"] == "Oro"
    assert rows[0]["Precio"] == "1000"
