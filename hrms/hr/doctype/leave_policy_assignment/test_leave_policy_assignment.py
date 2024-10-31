# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, get_first_day, get_year_ending, getdate

from hrms.hr.doctype.leave_application.test_leave_application import get_employee, get_leave_period
from hrms.hr.doctype.leave_period.test_leave_period import create_leave_period
from hrms.hr.doctype.leave_policy.test_leave_policy import create_leave_policy
from hrms.hr.doctype.leave_policy_assignment.leave_policy_assignment import (
	create_assignment,
	create_assignment_for_multiple_employees,
)
from hrms.hr.doctype.leave_type.test_leave_type import create_leave_type

test_dependencies = ["Employee"]


class TestLeavePolicyAssignment(IntegrationTestCase):
	def setUp(self):
		for doctype in [
			"Leave Period",
			"Leave Application",
			"Leave Allocation",
			"Leave Policy",
			"Leave Policy Assignment",
			"Leave Ledger Entry",
		]:
			frappe.db.delete(doctype)

		employee = get_employee()
		self.original_doj = employee.date_of_joining
		self.employee = employee

	def test_grant_leaves(self):
		leave_period = get_leave_period()
		leave_policy = create_leave_policy(annual_allocation=10)
		leave_policy.submit()

		self.employee.date_of_joining = get_first_day(leave_period.from_date)
		self.employee.save()

		data = frappe._dict(
			{
				"assignment_based_on": "Leave Period",
				"leave_policy": leave_policy.name,
				"leave_period": leave_period.name,
			}
		)
		assignments = create_assignment_for_multiple_employees([self.employee.name], data)
		self.assertEqual(
			frappe.db.get_value("Leave Policy Assignment", assignments[0], "leaves_allocated"),
			1,
		)

		allocation = frappe.db.get_value(
			"Leave Allocation", {"leave_policy_assignment": assignments[0]}, "name"
		)

		leave_alloc_doc = frappe.get_doc("Leave Allocation", allocation)

		self.assertEqual(leave_alloc_doc.new_leaves_allocated, 10)
		self.assertEqual(leave_alloc_doc.leave_type, "_Test Leave Type")
		self.assertEqual(getdate(leave_alloc_doc.from_date), getdate(leave_period.from_date))
		self.assertEqual(getdate(leave_alloc_doc.to_date), getdate(leave_period.to_date))
		self.assertEqual(leave_alloc_doc.leave_policy, leave_policy.name)
		self.assertEqual(leave_alloc_doc.leave_policy_assignment, assignments[0])

	def test_allow_to_grant_all_leave_after_cancellation_of_every_leave_allocation(self):
		leave_period = get_leave_period()
		leave_policy = create_leave_policy(annual_allocation=10)
		leave_policy.submit()

		data = frappe._dict(
			{
				"assignment_based_on": "Leave Period",
				"leave_policy": leave_policy.name,
				"leave_period": leave_period.name,
			}
		)
		assignments = create_assignment_for_multiple_employees([self.employee.name], data)

		# every leave is allocated no more leave can be granted now
		self.assertEqual(
			frappe.db.get_value("Leave Policy Assignment", assignments[0], "leaves_allocated"),
			1,
		)

		allocation = frappe.db.get_value(
			"Leave Allocation", {"leave_policy_assignment": assignments[0]}, "name"
		)

		leave_alloc_doc = frappe.get_doc("Leave Allocation", allocation)
		leave_alloc_doc.cancel()
		leave_alloc_doc.delete()
		self.assertEqual(
			frappe.db.get_value("Leave Policy Assignment", assignments[0], "leaves_allocated"),
			0,
		)

	def test_pro_rated_leave_allocation(self):
		leave_period = get_leave_period()
		leave_policy = create_leave_policy(annual_allocation=12)
		leave_policy.submit()

		self.employee.date_of_joining = add_months(leave_period.from_date, 3)
		self.employee.save()

		data = {
			"assignment_based_on": "Leave Period",
			"leave_policy": leave_policy.name,
			"leave_period": leave_period.name,
		}
		assignments = create_assignment_for_multiple_employees([self.employee.name], frappe._dict(data))

		allocation = frappe.db.get_value(
			"Leave Allocation", {"leave_policy_assignment": assignments[0]}, "new_leaves_allocated"
		)

		# pro-rated leave allocation for 9 months
		self.assertEqual(allocation, 9)

	# tests no of leaves for passed months if assignment is based on Leave Period / Joining Date
	def test_get_leaves_for_passed_months(self):
		first_day = get_first_day(getdate())
		annual_allocation = 10
		leave_type = create_leave_type(
			leave_type_name="_Test Earned Leave", is_earned_leave=True, allocate_on_day="First Day"
		)
		leave_policy = create_leave_policy(leave_type=leave_type, annual_allocation=annual_allocation)
		leave_policy.submit()

		data = {
			"assignment_based_on": "Joining Date",
			"leave_policy": leave_policy.name,
		}

		self.employee.date_of_joining = add_months(first_day, -5)
		self.employee.save()
		assignment = create_assignment(self.employee.name, frappe._dict(data))
		new_leaves_allocated = assignment.get_leaves_for_passed_months(
			annual_allocation, leave_type, self.employee.date_of_joining
		)
		self.assertEqual(new_leaves_allocated, 5)

		self.employee.date_of_joining = add_months(first_day, -35)
		self.employee.save()
		assignment = create_assignment(self.employee.name, frappe._dict(data))
		new_leaves_allocated = assignment.get_leaves_for_passed_months(
			annual_allocation, leave_type, self.employee.date_of_joining
		)
		self.assertEqual(new_leaves_allocated, 30)

		leave_period = create_leave_period(add_months(first_day, -23), first_day)
		data = {
			"assignment_based_on": "Leave Period",
			"leave_policy": leave_policy.name,
			"leave_period": leave_period.name,
		}
		assignment = create_assignment(self.employee.name, frappe._dict(data))
		new_leaves_allocated = assignment.get_leaves_for_passed_months(
			annual_allocation, leave_type, self.employee.date_of_joining
		)
		self.assertEqual(new_leaves_allocated, 20)

	def test_pro_rated_leave_allocation_for_custom_date_range(self):
		leave_type = frappe.get_doc(
			{
				"doctype": "Leave Type",
				"leave_type_name": "_Test Leave Type_",
				"include_holiday": 1,
				"is_earned_leave": 1,
				"allocate_on_day": "First Day",
			}
		).submit()

		leave_policy = frappe.get_doc(
			{
				"doctype": "Leave Policy",
				"title": "Test Leave Policy",
				"leave_policy_details": [
					{
						"leave_type": leave_type.name,
						"annual_allocation": 12,
					}
				],
			}
		).submit()

		today_date = getdate()

		leave_policy_assignment = frappe.new_doc("Leave Policy Assignment")
		leave_policy_assignment.employee = self.employee
		leave_policy_assignment.leave_policy = leave_policy.name
		leave_policy_assignment.effective_from = getdate(get_first_day(today_date))
		leave_policy_assignment.effective_to = getdate(get_year_ending(today_date))
		leave_policy_assignment.submit()

		new_leaves_allocated = frappe.db.get_value(
			"Leave Allocation",
			{
				"employee": leave_policy_assignment.employee,
				"leave_policy_assignment": leave_policy_assignment.name,
			},
			"new_leaves_allocated",
		)

		self.assertGreater(new_leaves_allocated, 0)

	def tearDown(self):
		frappe.db.set_value("Employee", self.employee.name, "date_of_joining", self.original_doj)
