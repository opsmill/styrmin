get_cluster_query = """
    query GetCluster($clusterId: UUID!) {
        cluster(clusterId: $clusterId) {
            id
            name
            config
            createdOn
            updatedOn
            environments {
                id
                name
            }
        }
    }
"""

get_clusters_query = """
    query GetClusters {
        clusters {
            id
            name
            config
            createdOn
            updatedOn
            environments {
                id
                name
            }
        }
    }
"""

create_cluster_query = """
    mutation CreateCluster($name: String!, $config: JSON) {
        createCluster(name: $name, config: $config) {
            id
            name
            config
        }
    }
"""

delete_cluster_query = """
    mutation DeleteCluster($clusterId: UUID!) {
        deleteCluster(clusterId: $clusterId)
    }
"""

create_environment_query = """
    mutation CreateEnvironment($name: String!, $clusterId: UUID!, $config: JSON) {
        createEnvironment(name: $name, clusterId: $clusterId, config: $config) {
            id
            name
            config
            cluster {
                id
                name
            }
        }
    }
"""

get_environment_query = """
    query GetEnvironment($environmentId: UUID!) {
        environment(environmentId: $environmentId) {
            id
            name
            cluster {
                id
                name
            }
        }
    }
"""

delete_environment_query = """
    mutation DeleteEnvironment($environmentId: UUID!) {
        deleteEnvironment(environmentId: $environmentId)
    }
"""

ok_query = """
    query HealthCheck {
        ok
    }
"""

callback_mutation = """
    mutation Callback($taskId: UUID!, $stateName: String!, $stateMessage: String, $stateType: String!) {
        callback(taskId: $taskId, stateName: $stateName, stateMessage: $stateMessage, stateType: $stateType) {
            message
            success
        }
    }
"""

get_deployment_query = """
    query GetDeployment($deploymentId: UUID!) {
        deployment(deploymentId: $deploymentId) {
            id
            name
            status
            internal
        }
    }
"""

update_deployment_mutation = """
    mutation UpdateDeployment($deploymentId: UUID!, $config: JSON!) {
        updateDeployment(deploymentId: $deploymentId, config: $config) {
            id
        }
    }
"""

update_deployment_version_mutation = """
    mutation UpdateDeploymentVersion($deploymentId: UUID!, $version: String!) {
        updateDeploymentVersion(deploymentId: $deploymentId, version: $version) {
            id
        }
    }
"""
