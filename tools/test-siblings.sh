# Quick test script used during development. This should obviously be replaced
# with actual tests.

# However, if you have repos locally in golang organization, and you have:
#   git.openstack.org/openstack-dev/pbr
#   git.openstack.org/openstack/keystoneauth
#   git.openstack.org/openstack/openstacksdk
#   git.openstack.org/openstack/pbrx
#   git.openstack.org/openstack/python-openstackclient
#   git.openstack.org/openstack/requirements
#   github.com/requests/requests
#
# You should be able to run this script in the openstack/python-openstackclient
# directory and verify it does the right things.
# openstack/python-openstackclient was selected because it exhibits a complex
# Entrypoints issue.
set -e

BASE=../../..
OPENSTACK=$BASE/git.openstack.org/openstack
for interp in python2 python3 ; do
    venv=venv-$interp
    rm -rf $venv
    virtualenv --python=$interp venv-$interp
    # Install python-openstackclient's requirements with constraings
    $venv/bin/pip install -c $OPENSTACK/requirements/upper-constraints.txt -r requirements.txt
    # Install python-openstackclient itself
    $venv/bin/pip install --no-deps -e .
    # Install pbrx with this patch
    $venv/bin/pip install -e $BASE/git.openstack.org/openstack/pbrx/
    # Run siblings
    $venv/bin/pbrx --debug install-siblings -c $OPENSTACK/requirements/upper-constraints.txt $OPENSTACK/keystoneauth $OPENSTACK/openstack/python-openstacksdk $BASE/github.com/requests/requests $BASE/git.openstack.org/openstack-dev/pbr/
    # openstack help should not break
    $venv/bin/openstack help
done
