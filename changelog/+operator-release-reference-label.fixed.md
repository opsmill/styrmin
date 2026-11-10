Fixed the operator rewriting the Ingress, Service, Secret and NetworkPolicy objects of every deployment every few seconds, because two periodic passes disagreed on their release-reference label
