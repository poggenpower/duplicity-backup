# Configure logging
import logging
from kubernetes import client, config
from typing import List, Dict, Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class K8sLocalStorageDiscovery:
    def __init__(self, storage_class_names: List[str] = ["local-storage"]):
        """
        Initializes the Kubernetes CoreV1Api client.
        Tries to load in-cluster configuration, falls back to kubeconfig if needed.
        """
        try:
            config.load_incluster_config()
            self.storage_class_names = storage_class_names
            logger.debug(f"Loaded in-cluster Kubernetes configuration, storage classes: {storage_class_names}")
        except config.ConfigException:
            config.load_kube_config()
            logger.exception("Loaded kubeconfig file for Kubernetes configuration")
        self.v1 = client.CoreV1Api()

    def get_local_storage_dirs_for_node(self, node: str) -> List[str]:
        """
        Retrieves local storage directories for a specific node by querying the Kubernetes API.

        Args:
            node (str): The name of the node to query.

        Returns:
            Dict[str, List[str]]: Dictionary mapping the node name to a list of directory paths.
        """
        logger.info(f"Retrieving local storage directories for node: {node}")
        all_dirs = self.list_local_storage_dirs_by_node()
        node_dirs = all_dirs.get(node, [])
        logger.info(f"Directories for node {node}: {node_dirs}")
        return node_dirs

    def list_local_storage_dirs_by_node(self) -> Dict[str, List[str]]:
        """
        Lists all PersistentVolumes with StorageClass 'local-storage', extracts their paths,
        and groups them by node based on node affinity.

        Returns:
            Dict[str, List[str]]: Dictionary mapping node names to lists of directory paths.
        """
        logger.info(
            f"Listing all PersistentVolumes with StorageClass {self.storage_class_names} and grouping by node"
        )
        pv_list = self.v1.list_persistent_volume()
        node_dirs = {}
        for pv in pv_list.items:
            sc = pv.spec.storage_class_name
            if sc in self.storage_class_names and pv.status.phase == "Bound":
                # Check for the "dubdir-skipp-backup" label
                labels = pv.metadata.labels or {}
                if "dubdir-skipp-backup" in labels:
                    logger.info(f"Skipping PersistentVolume {pv.metadata.name} due to 'dubdir-skipp-backup' label.")
                    continue  # Skip this PV and move to the next one                path = None
                if pv.spec.local.path:
                    path = pv.spec.local.path
                else:
                    logger.error(f"PersistentVolume {pv.metadata.name} does not have a local path defined.")
                    continue  # Skip this PV and move to the next one
                node_name = None
                # Discover node affinity from required terms
                if pv.spec.node_affinity and pv.spec.node_affinity.required:
                    for term in pv.spec.node_affinity.required.node_selector_terms:
                        for expr in term.match_expressions:
                            if expr.key == "kubernetes.io/hostname" and expr.values:
                                node_name = expr.values[0]
                if path and node_name:
                    node_dirs.setdefault(node_name, []).append(path)
        logger.info(f"Directories grouped by node: {node_dirs}")
        return node_dirs

    @staticmethod
    def discover_common_path(directories: List[str]) -> tuple[str, List[str]]:
        """
        Finds the longest common prefix (directory path) among a list of directories.
        Returns the common prefix and the list of directories with the prefix removed.

        Args:
            directories (List[str]): List of directory paths.

        Returns:
            tuple[str, List[str]]: (common_prefix, [dirs_without_prefix])
        """
        import os

        if not directories:
            return ("", [])

        # Find common prefix
        common_prefix = os.path.commonprefix(directories)
        # Ensure the prefix ends at a directory boundary
        common_prefix = (
            os.path.dirname(common_prefix)
            if not common_prefix.endswith(os.sep)
            else common_prefix
        )

        # Remove the common prefix from each directory
        dirs_without_prefix = [d[len(common_prefix):].lstrip(os.sep) for d in directories]

        return (common_prefix, dirs_without_prefix)
