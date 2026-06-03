from erpnext.stock.doctype.material_request.material_request import MaterialRequest


class CustomMaterialRequest(MaterialRequest):

    def validate_warehouse(self):
        from erpnext.stock.utils import (
            validate_disabled_warehouse,
            validate_warehouse_company
        )

        warehouses = list(
            set(d.warehouse for d in self.get("items")
            if getattr(d, "warehouse", None))
        )

        target_warehouses = list(
            set(d.target_warehouse for d in self.get("items")
            if getattr(d, "target_warehouse", None))
        )

        warehouses.extend(target_warehouses)

        from_warehouses = list(
            set(d.from_warehouse for d in self.get("items")
            if getattr(d, "from_warehouse", None))
        )

        if getattr(self, "set_from_warehouse", None):
            from_warehouses.append(self.set_from_warehouse)

        warehouses.extend(from_warehouses)

        for w in warehouses:

            # Always keep this validation
            validate_disabled_warehouse(w)

            # Skip company check only for Material Transfer
            if self.material_request_type == "Material Transfer":
                continue

            validate_warehouse_company(w, self.company)

        if self.material_request_type == "Material Transfer":
            self.validate_material_transfer_source_warehouses(from_warehouses)

    def validate_material_transfer_source_warehouses(self, from_warehouses):
        from qcmc_logic.utils import _validate_material_request_source_warehouse

        for warehouse in from_warehouses:
            _validate_material_request_source_warehouse(warehouse)
