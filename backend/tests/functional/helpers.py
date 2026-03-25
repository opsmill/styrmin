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

# --- Nested resolver test queries ---

get_deployment_with_environment_query = """
    query GetDeployment($deploymentId: UUID!) {
        deployment(deploymentId: $deploymentId) {
            id
            name
            environmentId
            environment {
                id
                name
            }
        }
    }
"""

get_deployment_with_adv_query = """
    query GetDeployment($deploymentId: UUID!) {
        deployment(deploymentId: $deploymentId) {
            id
            name
            applicationDriverVersionId
            applicationDriverVersion {
                id
                version
                applicationDriverId
            }
        }
    }
"""

get_deployment_backward_compat_query = """
    query GetDeployment($deploymentId: UUID!) {
        deployment(deploymentId: $deploymentId) {
            id
            name
            environmentId
            applicationDriverVersionId
        }
    }
"""

get_deployment_with_adv_and_driver_query = """
    query GetDeployment($deploymentId: UUID!) {
        deployment(deploymentId: $deploymentId) {
            id
            applicationDriverVersion {
                id
                version
                applicationDriver {
                    id
                    name
                }
            }
        }
    }
"""

get_backup_with_instance_adv_query = """
    query GetBackup($backupId: UUID!) {
        backup(backupId: $backupId) {
            id
            instance {
                id
                name
                applicationDriverVersion {
                    id
                    version
                }
            }
        }
    }
"""

get_task_with_deployment_query = """
    query GetTask($taskId: UUID!) {
        task(taskId: $taskId) {
            id
            deploymentId
            deployment {
                id
                name
            }
        }
    }
"""

get_backup_schedule_with_deployment_query = """
    query GetBackupSchedule($scheduleId: UUID!) {
        backupSchedule(scheduleId: $scheduleId) {
            id
            name
            deploymentId
            deployment {
                id
                name
            }
        }
    }
"""

get_backup_with_instance_query = """
    query GetBackup($backupId: UUID!) {
        backup(backupId: $backupId) {
            id
            name
            instanceId
            instance {
                id
                name
            }
        }
    }
"""

get_restore_with_backup_query = """
    query GetRestore($restoreId: UUID!) {
        restore(restoreId: $restoreId) {
            id
            name
            backupId
            backup {
                id
                name
            }
        }
    }
"""
