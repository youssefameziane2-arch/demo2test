"""Exemple : bibliothèque de steps d'une autre équipe, sans métadonnées demo2test.

demo2test la lit sans l'importer (analyse AST). Ses steps n'ont pas de ligne ``d2t:`` :
les règles ne peuvent pas les reconnaître, mais la recherche dans le catalogue et le
LLM peuvent s'y appuyer grâce à leur description.
"""
from pytest_bdd import given, parsers, when


@given("the NoC Config Studio is open")
def studio_open(studio):
    """Start the application with a blank design."""


@when(parsers.parse('I declare the CPU port "{name}" speaking {protocol}'))
def declare_cpu_port(studio, name, protocol):
    """Declare a processor initiator port on the interconnect, with its bus protocol."""


@when("I run the design rule check")
def run_drc(studio):
    """Run the design rule checks (DRC) of the network on chip."""
