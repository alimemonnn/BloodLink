# class collection:
# 	def __init__(self):
# 		self.items = []
# 	def create(self):
# 		self.items = []
# 		print("collection created")
# 	def insert(self, value):
# 		self.items.append(value)
# 		print("value has been inserted")
# 	def search(self, value):
# 		if value in self.items:
# 			print(value, "Founded")
# 		else:
# 			print("Not founded")
# 	def delete(self, value):
# 		if value in self.items:
# 			self.items.remove(value)	
# 			print("Remove", value)
# 		else:
# 			print("value not found")
# 	def traverse(self):
# 		if len(self.items) == 0:
# 			print("Collection Empty")
# 		else:
# 			for i in self.items:
# 				print(i)

# collection = collection()
# collection.create()

# collection.insert(1)
# collection.insert(2)
# collection.insert(3)
# collection.insert(4)
# collection.insert(5)

# collection.traverse()
# s = int(input("Enter value for search: "))
# collection.search(s)
# d = int(input("Enter value for delete: "))
# collection.delete(d)
# collection.traverse()
# # # # # # # # def sum(listt):
# # # # # # # #     sum = 0
# # # # # # # #     for i in listt:
# # # # # # # #         sum += i
# # # # # # # #     return sum
# # # # # # # # input_size = [1, 2, 3, 4, 5]
# # # # # # # # print("The sum of the list is: ", sum(input_size))

# # # # # # # import time
# # # # # # # def compare_pairs(data):
# # # # # # # 	comparisons = 0
# # # # # # # 	for i in data:
# # # # # # # 		for j in data:
# # # # # # # 			comparisons += 1
# # # # # # # 	return comparisons

	
# # # # # # # data = [1, 2, 3, 4, 5]
# # # # # # # start_time = time.perf_counter()
# # # # # # # total_comparisons = compare_pairs(data)
# # # # # # # end_time = time.perf_counter()
# # # # # # # execution_time = end_time - start_time
# # # # # # # print("Total Comparisons:", total_comparisons)
# # # # # # # print("Execution Time:", execution_time, "seconds")
# # # # # # # print("Time Complexity: O(n²)")
# # # # # # # Task-1: Create a dictionary containing information about a student. Search for the student's 
# # # # # # # semester using its key. Measure the execution time and identify the time complexity
# # # # # # # dic = {
# # # # # # # 	"name": "John Doe",
# # # # # # # 	"age": 20,
# # # # # # # 	"semester": 4,
# # # # # # # 	"major": "Computer Science"
# # # # # # # }
# # # # # # # print("Student's semester: ", dic["semester"])
# # # # # # # Create a Python function that finds the highest mark from a list of student marks. Measure 
# # # # # # # the execution time and identify the time complexity. Task-3: Create a Python program using nested loops
# # # # # # def highest_marks(marks):
# # # # # #     highest = marks[0]
# # # # # #     for mark in marks:
# # # # # #         if marks>highest:
# # # # # #             highest = mark
# # # # # #         elif mark == highest:
# # # # # #             print("There are multiple students with the highest mark:", highest)
# # # # # #         else:
# # # # # #             continue
# # # # # # def marks(markss):
# # # # # #     highest = markss[0]
# # # # # #     for mark in markss:
# # # # # #         if mark > highest:
# # # # # #             highest = mark
# # # # # #         else:
# # # # # #             continue
# # # # # #     return highest
# # # # # # list_of_marks = [12,3,4,55,2,14,56,77,54,22,100,200,3000,71,89,99]

# # # # # # # print("The highest mark is: ", marks(list_of_marks))

# # # # # # n = int(input("Enter n number: "))
# # # # # # for i in range(n):
# # # # # #     for j in range(10):
# # # # # #         print((i+1),"X",(j+1),"=", (i+1)*(j+1))


# # # # # # listt = ["Muhammmad Ali","Ali Afzal"]
# # # # # # print("Original List: ",listt)
# # # # # # listt.append("ALI Memon")
# # # # # # print(listt)
# # # # # # listt.insert(3,"Ali Khan")
# # # # # # print(listt)
# # # # # # listt.remove(listt[2])
# # # # # # print(listt)
# # # # # # listt[0] = "Memon"
# # # # # # print(listt)

# # # # # # A weather monitoring application stores the daily temperatures of a week 
# # # # # # in a list. Display all temperatures, calculate 
# # # # # # the highest and lowest temperature, and calculate the average.

# # # # # def Highest_temp(listt):
# # # # #     highest = listt[0]
# # # # #     for temp in listt:
# # # # #         if temp > highest:
# # # # #             highest = temp
# # # # #     return highest
# # # # # def lowest_temp(listt):
# # # # #     lowest = listt[0]
# # # # #     for temp in listt:
# # # # #         if temp < lowest:
# # # # #             lowest = temp
# # # # #     return lowest
# # # # # def average_temp(listt):
# # # # #     total = 0
# # # # #     for temp in listt:
# # # # #         total += temp
# # # # #     average = total / len(listt)
# # # # #     return average


# # # # # listt = [33,40,37,29,35,38,42]
# # # # # total = 0
# # # # # print("The temperatures of the week are: ", listt)
# # # # # print("The highest temperature is: ", Highest_temp(listt))
# # # # # print("The lowest temperature is: ", lowest_temp(listt))
# # # # # print("The average temperature is: ", average_temp(listt))

# # # # 12: A classroom application maintains a list of student names. 
# # # # A new student joins, one student
# # # # leaves, and one student's name must be corrected.
# # # # Implement all three operations.

# # # # student = ["Ali","Umar","Adil","yousuf"]
# # # # print("Original List: ",student)
# # # # student.append("Ahmed")
# # # # print("After adding a new student: ",student)
# # # # student.remove("Adil")
# # # # print("After removing a student: ",student)
# # # # student[0] = "Muhammad Ali"
# # # # print("After correcting a student's name: ",student)

# # # # 13: Create an unsorted list of at least 12 integers
# # # # and search for a user-defined target using Linear
# # # # Search.
# # # # Task 13: Linear Search

# # # # Create an unsorted list of at least 12 integers
# # # numbers = [45, 12, 78, 23, 56, 9, 34, 67, 89, 15, 42, 31]

# # # print("List:", numbers)

# # # # Take target from user
# # # target = int(input("Enter the target value to search: "))

# # # # Linear Search
# # # found = False

# # # for i in range(len(numbers)):
# # #     if numbers[i] == target:
# # #         print("Target found!")
# # #         print("Value:", numbers[i])
# # #         print("Index:", i)
# # #         found = True
# # #         break

# # # if found == False:
# # #     print("Target not found.")

# # # numbers = [100,1,4,5,9,10,2,3,4,5,200,0]
# # # found = False
# # # print("List: ", numbers)
# # # t = int(input("Enter the target value to search: "))
# # # for i in range(len(numbers)):
# # #     if numbers[i] == t:
# # #         print("Target found!")
# # #         print("value: ", numbers[i])
# # #         print("Index: ", i)
# # #         found = True
# # # if found == False:
# # #     print("Target not found")
 
# # products = ["Keyboard", "Mouse", "Monitor", "Printer"]

# # print("Original list:", products)

# # products[1] = "Wireless Mouse"
# # print("After index-based update:", products)

# # old_value = "Printer"
# # new_value = "Scanner"

# # for i in range(len(products)):
# #     if products[i] == old_value:
# #         products[i] = new_value
# #     break

# # print("After search-based update:",products)

# # l = [10,9,7,3,1,20,17,405,100]
# # print(l)
# # target = int(input("Enter the target value to search:"))
# # found = False
# # for i in range(len(l)):
# #     if l[i] == target:
# #         print("Target found!")
# #         print("Value: ", l[i])
# #         print("Index: ", i)
# #         found = True
# #     break

# # if found == False:
# #     print("Target not found.")

# # Take target import numbers

# # import numbers

# import numbers

# from user
# target = int(input("Enter the target value to search: "))

# # Linear Search
# found = False

# for i in range(len(numbers)):
#     if numbers[i] == target:
#         print("Target found!")
#         print("Value:",numbers[i])
#         print("Index:", i)
#         found = True
#         break

# if found == False:
#     print("Target not found.")


# numbers = [10,9,7,3,1,20,17,405,100]

# print("original List: ", numbers)
# target = int(input("Enter your target to search: "))
# found = -1
# for i in range(len(numbers)):
#     if numbers[i] == target:
#         print("value is founded: ",target)
#         print("Index: ", i)
#         found = 1
# if found == -1:
#     print("Target is not found")


# class Collection:
#     def __init__(self):
#         self.items = []
#     def create(self):
#         self.items = []
#         print("Collection is created")
#     def insert(self,value):
#         self.items.append(value)
#         print("Value is inserted", value)
#     def traverse(self):
#         for i in self.items:
#             print(i)
#     def search(self, value):
#         for i in self.items
# scores = [55, 72, 55, 81, 90, 55, 68]
# target = 55

# positions = []

# for i in range(len(scores)):
#     if scores[i] == target:
#         positions.append(i)

# print("Scores:", scores)
# print("Target:", target)

# if positions:
#     print("Target found at indexes:", positions)
# else:
#     print("Target not found")

# from operator import pos


# from turtle import position


# numbers = [10,2,4,5,1,3,2,4,5,10,23,4,23]
# target = int(input("Enter your target: "))
# print("Original list: ",numbers)
# position = []
# for i in range(len(numbers)):
#     if target == numbers[i]:
#         position.append(i)

# if positions:
#     print("Target found at indexes:", positions)
# else:
#     print("Target not found")
 
# from asyncio import Task


# Task 14: A store keeps recently scanned product IDs
# in an unsorted list. Search for a requested product ID
# and report whether it exists and at which position.

# numbers = [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]
# print("sorted list: ",numbers)
# target = int(input("Enter your target: "))
# beg = 0
# end = len(numbers)-1
# found = -1
# while beg<=end:
#     mid = (beg+end)//2
#     if numbers[mid] == target:
#         found = mid
#         break
#     elif numbers[mid] > target:
#         beg = mid
#     else:
#         end = mid-1
# print("Sorted list:", numbers)
# print("Target:", target)
# numbers = [10, 20, 30, 40, 50, 60, 70, 80, 90]
# target = 70

# beg= 0
# end = len(numbers) - 1
# found_index = -1

# while beg <= end:
#     mid = (beg + end) // 2

#     if numbers[mid] == target:
#         found_index = mid
#         break
#     elif numbers[mid] > target:
#         beg = mid + 1
#     else:
#         end = mid - 1

# print("Sorted list:", numbers)
# print("Target:", target)

# numbers = [10, 20, 30, 40, 50, 60, 70, 80, 90]
# beg = 0
# end = len(numbers) - 1
# found_index = -1
# print(numbers)
# target = int(input("Enter your target: "))
# while beg<=end:
#     mid = (beg+end)//2
#     if numbers[mid] == target:
#         found_index = mid
#         print("Value found on index: ",found_index)
#         break
#     elif numbers[mid] < target:
#         beg = mid + 1
#     elif numbers[mid]>target: 
#         end = mid -1
   

# print("Sorted list:", numbers)
# print("Target:", target)

# if found_index != -1:
#     print("Target found at index:", found_index)    
# else:
#     print("Target not found")

# Take name and age, print 'Hello NAME, you are AGE years old'
# name = input("Enter your name: ")
# age = int(input("Enter your age: "))
# print("Hello ",name, "you are", age, "years old")

# # • Task 2: Take radius and calculate area of circle (πr², π=3.14)
# radius = float(input("Enter the radius of the circle: "))
# area = 3.14 * radius*radius
# print("The area of the circle is: ", area)

# • Task 3: Take marks of 3 subjects, calculate total and percentage
# sub1 = float(input("Enter marks of subject 1: "))
# sub2 = float(input("Enter marks of subject 1: "))
# sub3 = float(input("Enter marks of subject 1: "))
# total = sub1+sub2+sub3
# percentage = (total/300)*100
# print("Total marks: ", total, "Percentage: ", percentage, "%")
# # • Task 4: Swap two numbers without third variable (hint: a,b = b,a)
# a = 10
# b = 20
# # print("before swapping: a =",a, "b = ", b)
# # a,b = b,a
# # print("After swapping: a= ", a,  " b = " ,b)
# # # • Task 5: Check if number is even or odd using % operator
# def main():
#     # A while loop keeps the program active until the user chooses to exit
#     while True:
#         print("\n======================================")
#         print("       SMART DECISION ENGINE MENU     ")
#         print("======================================")
#         print("1. Drone Battery & Altitude Check (if / if-else)")
#         print("2. Autonomous Driving Mode (match-case)")
#         print("3. Rocket Countdown System (while loop)")
#         print("4. Sensor Grid Matrix Scanner (nested for loop)")
#         print("5. Exit Program")
#         print("--------------------------------------")
        
#         try:
#             choice = int(input("Enter your choice (1-5): "))
#         except ValueError:
#             print("\nInvalid input! Please enter a valid number.")
#             continue

#         if choice == 1:
#             # 1. Selection Statements: if, elif, and compound conditionals
#             print("\n--- [Drone Telemetry Check] ---")
#             battery_level = int(input("Enter battery percentage (0-100): "))
#             altitude = float(input("Enter altitude (meters): "))

#             # Compound conditional using logical AND (and)
#             if battery_level < 20 and altitude > 50.0:
#                 print(">> ALERT: Battery low and altitude high! Engaging auto-descent.")
#             elif battery_level >= 20 and altitude > 0:
#                 print(">> Status: Flight parameters normal. Systems operational.")
#             elif altitude <= 0:
#                 print(">> Status: Drone is currently grounded.")
#             else:
#                 print(">> Status: Safe landing recommended.")

#         elif choice == 2:
#             # 2. Selection Statement: match-case (Python's equivalent to switch-case)
#             print("\n--- [Autonomous Vehicle Drive Mode] ---")
#             mode = input("Select mode (E: Eco, S: Sport, A: Autonomous Pilot): ").strip()

#             # Convert input to uppercase to handle both 'e' and 'E' efficiently
#             match mode.upper():
#                 case 'E':
#                     print(">> Eco Mode: Maximum efficiency enabled.")
#                 case 'S':
#                     print(">> Sport Mode: Maximum acceleration unlocked.")
#                 case 'A':
#                     print(">> AutoPilot: LiDAR sensors and lane assistance active.")
#                 case _:
#                     print(">> Invalid drive mode selected.")

#         elif choice == 3:
#             # 3. Entry-Controlled Loop: while loop
#             print("\n--- [Rocket Engine Ignition Sequence] ---")
#             countdown = 5

#             while countdown > 0:
#                 print(f"T-minus {countdown} seconds...")
#                 countdown -= 1
#             print(">> Liftoff! Rocket booster stage active.")

#         elif choice == 4:
#             # 4. Nested Loops: nested for loop with continue statement
#             print("\n--- [Sensor Grid Calibration (3x3 Matrix)] ---")
#             for row in range(1, 4):
#                 for col in range(1, 4):
#                     # Skip calibration for the center cell (2, 2)
#                     if row == 2 and col == 2:
#                         print("[Center-SKIP] ", end="")
#                         continue
#                     print(f"[Node {row},{col}] ", end="")
#                 print()  # Move to next row (prints a newline)

#         elif choice == 5:
#             print("\nShutting down system. Goodbye!")
#             break

#         else:
#             print("\nInvalid choice! Please select an option between 1 and 5.")

# if __name__ == "__main__":
#     main()

# word = input("Enter a word: ")
# rev_word = word[::-1]  # reverse string
# if word == rev_word:
#     print(f"{word} is a Palindrome!")
# else:
#     print(f"{word} is NOT a Palindrome.")

# word = input("Enter a word: ")
# rev_word = word[::-1]
# if word == rev_word:
#     print(word, "is a Palindrome!")
# else:
#     print(word, "is NOT a Palindrome.")

# l = [10,22,28,60,180]
# total = 0
# maximum = l[0]
# for i in l:
#     if i > maximum:
#         maximum = i
#     total += i
# print("The sum of the list is: ", total)
# print("The maximum value in the list is: ", maximum)
# t = (1, 2, 2, 3, 4, 2, 5,10)
# # print("Count of 1:", t.count(1))
# print( "Index of first occurrence of 10:", t.index(10))

l = [10, 22, 28, 60, 180]
s = set(l)
print(type(s))
print(type(l))