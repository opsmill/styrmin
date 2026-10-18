# The Semaphore image of demos 2 to 4: Semaphore with the Infrahub Ansible collection and the demo playbook (research R-009).
FROM semaphoreui/semaphore:v2.16.47

USER root
# Semaphore runs ansible-playbook with HOME in /tmp, so the collection goes to a system path.
# opsmill.infrahub 1.8.3 is the last release that supports the image's ansible-core 2.18.
RUN mkdir -p /usr/share/ansible/collections \
 && ansible-galaxy collection install 'opsmill.infrahub:==1.8.3' -p /usr/share/ansible/collections \
 && chown -R 1001:0 /usr/share/ansible
COPY --chown=1001:0 ansible /opt/demo/ansible

USER 1001
RUN pip install --no-cache-dir 'infrahub-sdk>=1.19,<2'
