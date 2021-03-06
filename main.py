########################################################################################################################
# Made by: Justin Trujillo - jtrujillo923@gmail.com
# Made for: WeLink Communications Technical Support
# License: GPLv3
########################################################################################################################
import paramiko
from icmplib import traceroute, async_multiping, ping
from mac_vendor_lookup import MacLookup
import ipaddress
import threading
import logging
import sys
import asyncio
import json
from prettytable import PrettyTable
import datetime
import arrow
import os

import EeroTests

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def cred_grab(user=None, pswd=None, port=None):
    while True:
        user = input("Please enter username: ")
        if user == '':
            print("User can't be blank, please try again...")
            continue
        else:
            break
    while True:
        pswd = input("Please enter password: ")
        if pswd == '':
            print("Password can't be blank, please try again...")
            continue
        else:
            break
    while True:
        while True:
            try:
                port = int(input("Please enter port: "))
                if port < 1 or port > 65535:
                    print("Port number must be an integer between 1-65535")
                    continue
                else:
                    break
            except TypeError:
                print("Port number must be an integer between 1-65535")
            except Exception as err:
                print(err)
                continue
        if port == '':
            print("Port can't be blank, please try again...")
            continue
        else:
            break
    return user, pswd, port


def cred_check(user=None, pswd=None, port=None, redo=True, hop_info=None, ip_list=None):
    # if hop_info is not None:
    #     hop1 = None
    #     i = 1
    #     for hop in ip_list:
    #         hop_info[hop] = {}
    #         if hop1 is None:
    #             hop1 = hop
    #         print(f"Grabbing info for hop {i} - {hop}")
    #         user, pswd, port = cred_grab(user, pswd, port)
    #         hop_info[hop]['user'] = user
    #         hop_info[hop]['pswd'] = pswd
    #         hop_info[hop]['port'] = port
    #         i += 1
    #     return hop_info[hop1]['user'], hop_info[hop1]['pswd'], hop_info[hop1]['port']
    # else:
    if user is None and pswd is None:
        user, pswd, port = cred_grab()
    else:
        if redo is True:
            while True:
                choice = input("Enter different credentials? (y/N): ")
                if choice == "Y" or choice == "y":
                    user, pswd, port = cred_grab(user, pswd, port)
                    break
                elif choice == "N" or choice == "n" or choice == '':
                    print("Trying with previous credentials...")
                    break
                else:
                    print("Invalid input, please try again...")
                    continue
    return user, pswd, port


def ip_check():  # Return string if IP is valid, else return 0
    ###
    # Get MBU IPv6 from user. Strip any whitespace and check if valid.
    ###
    while True:
        try:
            target_ip = str(input("\nWhat is the target MBU IPv6? (0 to exit): ")).strip()
            if target_ip == 0 or target_ip == "0":
                return 0
            if ipaddress.IPv6Address(target_ip):
                reachable = ping(target_ip)
                if reachable.packet_loss == 0.0:
                    break
                else:
                    table = PrettyTable(["IP", "Reachable"])
                    table.add_row([target_ip, "No"])
                    print(table)
                    return 0
            else:
                print("Invalid IPv6")
                continue
        except ValueError:
            print("Invalid IPv6")
    return target_ip


def hop_to_ip(hops, prefix):
    ###
    # Remove any hops that are not in the WeLink network
    # All hops in the WeLink network will have the same prefix as each other
    # i.e. fd8d:xxxx:xxxx:xx00::1 fd8d could be the prefix and all hops will start with fd8d
    ###
    ip_list = []
    for hop in hops:
        if prefix not in hop.address:
            continue
        ip_list.append(hop.address)
    return ip_list


def ip_format(imported_ip_list):
    ###
    # The last 2 digits of the IPv6 before `::1` are the interface number
    # To reach the MBU no matter what interface is up, we need to replace the last 2 digits with `00`
    ###
    ip_list = imported_ip_list
    formatted_ip_list = []
    for ip in ip_list:
        ###
        # We do not want to format leaf addresses, so we check if the ip ends in ::1 first
        # If it does, we format
        # If it does not, we skip
        ###
        test = ip[len(ip) - 3:]
        if test == '::1':
            ip_split = ip.split(":")

            if len(ip_split[len(ip_split) - 3]) > 1:
                ip_split[len(ip_split) - 3] = ip_split[len(ip_split) - 3][:-2] + "00"

            formatted_ip_list.append(":".join(ip_split))
        else:
            formatted_ip_list.append(ip)
    return formatted_ip_list


def ptmp_check(myconn=None, ip=None, user=None, pswd=None, port=None):
    ###
    # Check if the target MBU has a PTMP radio and if so, get the IPv6 for it
    # Also grab the leaf homes PTMP radio IPv6
    ###
    if myconn is None:
        myconn = paramiko.SSHClient()
        myconn.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        myconn.connect(ip, username=user, password=pswd, port=port)
    remote_cmd = 'grep -B 2 -ci ptmp /tmp/run/lldp_server.json'  # Check if PTMP radio is present
    stdin, stdout, stderr = myconn.exec_command(remote_cmd)
    out = "{}".format(stdout.read())
    out = out[2:-3]
    ptmp_table = PrettyTable(['IPv6', 'Eth Port', 'Address'])
    if out == 0 or out == "0":
        ptmp_table.add_row(["No PTMPs found", "N/A", get_address(myconn=myconn, ip=ip)])
        myconn.close()
        return ptmp_table
    else:
        remote_cmd = 'grep -i -B 2 ptmp /tmp/run/lldp_server.json | grep -io eth[0-4]'  # Get MBU Eths of PTMP radios

        stdin, stdout, stderr = myconn.exec_command(remote_cmd)
        out = "{}".format(stdout.read())
        out = out[2:-3]
        out = out.split("\\n")  # We now have all MBU Eth ports

        eths = {}
        ips = []
        for eth in out:
            remote_cmd = f'ip -6 neigh | grep -i \"{eth}\" | grep -v \"fe80\" | grep -i ll'  # Get IPv6 of PTMP radios
            stdin, stdout, stderr = myconn.exec_command(remote_cmd)
            output = "{}".format(stdout.read())
            output = output[2:-3]
            output = output.split("\\n")  # We now have IPv6 addresses

            for ip in output:
                new_ip = ip.split(" ")[0]
                ips.append(new_ip)
                eths[new_ip] = ip.split(" ")[2]

        for ip in ips:
            ptmp_table.add_row([ip, eths[ip], get_address(None, ip, user=user, pswd=pswd, port=port)])
        myconn.close()
        return ptmp_table


def get_mac(myconn=None, ip=None, user=None, pswd=None, port=None):
    ###
    # Get the MAC address of the device connected to MBU customer interface
    ###
    if myconn is None:  # If no previous ssh connection made, make one
        close = True
        myconn = paramiko.SSHClient()
        myconn.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        myconn.connect(ip, username=user, password=pswd, port=port)
    else:
        close = False
    ###
    # Get MAC from target with grep extracting from MBU bridge table
    ###
    remote_cmd = 'bridge fdb show | grep -iE \"dev (ghn0|eth[0-4]) master br\" | grep -v \"c4:93:00\"'
    (stdin, stdout, stderr) = myconn.exec_command(remote_cmd)
    out = "{}".format(stdout.read())
    out = str(out[2:].split()[0])
    if close:  # If we made a new connection, close it. If the session was called with the function it can still be used
        myconn.close()
    return out


def get_address(myconn=None, ip=None, user=None, pswd=None, port=None):
    ###
    # Return hostname of the MBU
    # Translates to LinkView site name
    ###
    if myconn is None:
        close = True
        myconn = paramiko.SSHClient()
        myconn.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        myconn.connect(ip, username=user, password=pswd, port=port)
    else:
        close = False
    remote_cmd = 'grep hostname /tmp/config.json'
    (stdin, stdout, stderr) = myconn.exec_command(remote_cmd)
    out = "{}".format(stdout.read())
    out = out.split()
    out = out[len(out) - 1]
    out = out.split(",")[0]
    out = out.split(".")[1]
    if out[len(out) - 1] == "\"":
        out = out[:-1]
    if close:
        myconn.close()
    return out


async def async_mtr(ips, hop_info):
    ###
    # Async mtr function
    # In theory this should be able to run in parallel with the rest of the code in the future
    # Would allow for checking if path changes while troubleshooting
    ###
    mtr_results = {}
    for ip in ips:
        mtr_results[ip] = {}
    total_pings = 1
    while total_pings != 0:
        try:
            total_pings = int(input("How many pings would you like to send? "))
            if total_pings == 0:
                return "Cancelled MTR"
            else:
                break
        except ValueError:
            print("Please enter a number.")
            continue
    print("Initializing MTR...")
    for ip in ips:  # Initialize
        mtr_results[ip]['address'] = 0
        mtr_results[ip]['rtt'] = 0
        mtr_results[ip]['packets_sent'] = 0
        mtr_results[ip]['packets_received'] = 0
        mtr_results[ip]['packet_loss'] = 0
        mtr_results[ip]['jitter'] = 0

    pingnum = 1
    while True:
        try:
            if pingnum > total_pings:
                break
            await asyncio.sleep(0.25)
            # print(route_change_check(target_ip, prefix, ips, hop_info))
            response = await async_multiping(ips, count=1)
            print(f"\n\n\n\n\n\n\n\n\n\n")
            mtr_table = PrettyTable(['IP', 'Address', 'RTT', 'Packets Sent',
                                     'Packets Received', 'Packet Loss', 'Jitter'])
            for host in response:
                ip = host.address
                mtr_results[ip]['address'] = hop_info[ip]['address']
                mtr_results[ip]['rtt'] = host.avg_rtt
                mtr_results[ip]['packets_sent'] = mtr_results[ip]['packets_sent'] + host.packets_sent
                mtr_results[ip]['packets_received'] = mtr_results[ip]['packets_received'] + host.packets_received
                mtr_results[ip]['packet_loss'] = mtr_results[ip]['packet_loss'] + host.packet_loss
                mtr_results[ip]['jitter'] = (mtr_results[ip]['jitter'] + host.jitter) / pingnum
                mtr_table.add_row([ip, mtr_results[ip]['address'], mtr_results[ip]['rtt'],
                                   mtr_results[ip]['packets_sent'], mtr_results[ip]['packets_received'],
                                   mtr_results[ip]['packet_loss'], mtr_results[ip]['jitter']])

            print(mtr_table)
            pingnum += 1

        except KeyboardInterrupt:
            print("\n\n\t\tFinished MTR\n\n")


def mtr(ips, hop_info):
    ###
    # mtr synchronous to asynchronous function
    ###
    asyncio.run(async_mtr(ips, hop_info))


def get_version(myconn=None, ip=None, user=None, pswd=None, port=None):
    ###
    # Return firmware version of the MBU
    ###
    if myconn is None:
        close = True
        myconn = paramiko.SSHClient()
        myconn.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        myconn.connect(ip, username=user, password=pswd, port=port)
    else:
        close = False
    remote_cmd = 'grep rev /usr/lib/release/firmux'
    (stdin, stdout, stderr) = myconn.exec_command(remote_cmd)
    version = "{}".format(stdout.read())
    version = version[2:-3]
    if close:
        myconn.close()
    return version


def route_print(hop_info):
    ###
    # Prints the full route table
    # Maybe a good idea to use PrettyTable for this instead for consistency
    ###
    i = 1
    for ip in hop_info:
        print(f"Hop {i} = {ip}\n"
              f"\tAddress = {hop_info[ip]['address']}\n"
              f"\tMBU Version = {hop_info[ip]['version']}\n"
              f"\tRouter MAC = {hop_info[ip]['router']['mac']}\n"
              f"\tRouter OUI = {hop_info[ip]['router']['oui']}")
        if hop_info[ip]['router']['url'] != "N/A":
            print(f"\tRouter URL = https://dashboard.eero.com/networks/{hop_info[ip]['router']['url']}")
        if hop_info[ip]['conflict'] is True:
            print(f"\tChannel conflict detected!!!!!!!!")
        i += 1


def gather_route(ip_list, hops=None, user=None, pswd=None, port=None, check=True):
    ###
    # Gathers the route table and all information for each hop
    ###
    if hops is None:
        hops = {}
    if ip_list is None:
        ip_list = []

    while True:
        choice = input("Do any hops use different credentials? (y/N): ")
        if choice == "Y" or choice == "y":
            check = True
            print("We will now gather credentials for each hop.")
            # user, pswd, port = cred_check(user, pswd, port, check, hop_info, ip_list)
            break
        elif choice == "N" or choice == "n" or choice == '':
            # print("Please give the credentials for the path.")
            check = False
            user, pswd, port = cred_check(user, pswd, port, check)
            print("Continuing...")
            break
        else:
            print("Invalid input. Please try again.")
            continue

    def channel_check(myconn, target_ip):
        ###
        # Checks if a channel is assigned to multiple radios on the same MBU
        ###
        remote_cmd = 'ls /tmp/run/ | grep -i stats | grep -i eth'  # Stats are in /tmp/run/stats_{eth[1-4]/
        (stdin, stdout, stderr) = myconn.exec_command(remote_cmd)
        eths = "{}".format(stdout.read())[2:-3].split("\\n")
        conflict = False
        chan_eth = {}
        channels = []

        for eth in eths:
            remote_cmd = f'grep -iE ".*" /tmp/run/{eth}/wireless.json'  # Channels in wireless.json
            (stdin, stdout, stderr) = myconn.exec_command(remote_cmd)
            out = str("{}".format(stdout.read())[2:-1].replace("\\n", ""))
            data = json.loads(out)
            chan = data['radios']['wlan0']['channel']

            if chan not in channels:
                channels.append(chan)
                chan_eth[eth[6:]] = chan
            else:
                print(f"Channel conflict detected on channel {chan} at {get_address(ip=target_ip)}!!!!!!!!")
                conflict = True
        return conflict

    def go_check(target_ip, user, pswd, port, check):
        i = 1
        myconn = None
        while True:
            try:
                if myconn is None:
                    myconn = paramiko.SSHClient()  # Create SSH connection for hop
                    myconn.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                if check:
                    print(f"\nEnter credentials for {target_ip}")
                    user, pswd, port = cred_check(user, pswd, port, check)
                    hops[target_ip]['user'] = user
                    hops[target_ip]['pswd'] = pswd
                    hops[target_ip]['port'] = port
                    myconn.connect(target_ip, username=user, password=pswd, port=port)
                else:
                    myconn.connect(target_ip, username=user, password=pswd, port=port)

                # hop_info[target_ip] = {}
                hops[target_ip]['conflict'] = channel_check(myconn, target_ip)
                hops[target_ip]["address"] = get_address(myconn)
                hops[target_ip]["router"] = {}
                mac = str(get_mac(myconn, target_ip))
                hops[target_ip]["router"]["mac"] = mac
                # print(mac)
                if mac == "\'":
                    hops[target_ip]["router"]["mac"] = "N/A"
                    hops[target_ip]["router"]["oui"] = "N/A"
                    hops[target_ip]["router"]["url"] = "N/A"
                else:
                    oui = MacLookup().lookup(mac)
                    hops[target_ip]["router"]["oui"] = oui
                    if hops[target_ip]["router"]["oui"] == "eero inc.":
                        url, serial = EeroTests.search_by_mac(mac=mac)
                        if url != "Missing Network" and serial != "Missing Serial":

                            hops[target_ip]["router"]["url"] = url
                            hops[target_ip]["router"]["serial"] = serial
                        else:
                            hops[target_ip]["router"]["url"] = "N/A"
                            hops[target_ip]["router"]["serial"] = "N/A"
                    else:
                        hops[target_ip]["router"]["url"] = "N/A"
                        hops[target_ip]["router"]["serial"] = "N/A"
                hops[target_ip]["version"] = get_version(myconn)
                myconn.close()
                break
            except paramiko.ssh_exception.AuthenticationException:
                print(f"Error authenticating with {ip}, please check credentials")
                return user, pswd, port, True
            except Exception as err:
                i += 1
                if i > 3:
                    print(f"\n\tHaving trouble connecting to {target_ip}.")
                    return True
                else:
                    print(f"\n\tUnable to connect to {target_ip}. Trying again.")
                    continue
        return user, pswd, port, False

    try_again = True
    fail = False
    for ip in ip_list:
        hops[ip] = {}
        try:
            hops[ip]['user'] = user
            hops[ip]['pswd'] = pswd
            hops[ip]['port'] = port
            while True:
                try:
                    if try_again:
                        user, pswd, port, fail = go_check(ip, user, pswd, port, check)
                    if fail:
                        print(f"Failed to connect to {ip}. Maybe the credentials are wrong?")
                        while True:
                            try:
                                c = input("\tDo you want to try again? (y/n): ")
                                if c == "y" or c == "Y" or c == "":
                                    user, pswd, port = cred_check(None, None, None, True)
                                    hops[ip]['user'] = user
                                    hops[ip]['pswd'] = pswd
                                    hops[ip]['port'] = port
                                    try_again = True
                                    break
                                elif c == "n" or c == "N":
                                    try_again = False
                                    break
                                else:
                                    print("\n\tInvalid input.")
                            except Exception as e:
                                print(f"\n\tError: {e}")
                                continue
                    if try_again is False:
                        break
                    else:
                        print(f"Finished grabbing info from {ip} - {hops[ip]['address']}.")
                        break
                except Exception as e:
                    print(f"\n\tError: {e}")
                    continue
            if try_again is False:
                break
        except Exception as e:
            print(f"\n\tError: {e}")
            break
    return hops, fail


def route_change_check(target_ip, prefix, ip_list, hop_info, user=None, pswd=None, port=None):
    ###
    # Checks if the route table has changed
    # Prints out difference if there has been changes
    # *important to note, the ips are all formatted to end in '00::1' to ignore changes in MBU interface
    ###
    new_traceroute = traceroute(target_ip)
    new_ip_list = hop_to_ip(new_traceroute, prefix)
    new_ip_list = ip_format(new_ip_list)
    new_hop_info = {}

    check = True
    user, pswd, port = None, None, None
    if new_ip_list != ip_list:
        print(f"Route has changed, checking new route...")
        for ip in new_hop_info:
            new_hop_info[ip] = {}
            new_hop_info[ip]['user'] = user
            new_hop_info[ip]['pswd'] = pswd
            new_hop_info[ip]['port'] = port
        while True:
            choice = input("Do any hops use different credentials? (y/N): ")
            if choice == "Y" or choice == "y":
                check = True
                print("We will now gather credentials for each hop.")
                # user, pswd, port = cred_check(user, pswd, port, check, hop_info, ip_list)
            elif choice == "N" or choice == "n" or choice == '':
                print("Please give the credentials for the path.")
                user, pswd, port = cred_check(user, pswd, port, check)
                check = False
                print("Continuing...")
                break
            else:
                print("Invalid input. Please try again.")
                continue
        new_hop_info, fail = gather_route(new_ip_list, new_hop_info, user, pswd, port, check)
        route_change = PrettyTable(["Hop Number", "Original Route", "Original Address", "New Route", "New Address"])
        if len(new_ip_list) > len(ip_list):
            for i in range(len(new_ip_list)):
                try:
                    route_change.add_row([i + 1, ip_list[i], hop_info[ip_list[i]]['address'],
                                          new_ip_list[i], new_hop_info[new_ip_list[i]]['address']])
                except IndexError:
                    try:
                        route_change.add_row([i + 1, "", "", new_ip_list[i], new_hop_info[new_ip_list[i]]['address']])
                    except Exception as e:
                        print(e)
                        logger.exception(e)
                        print(f"{new_ip_list[i]} is not reachable")
                        return
                except Exception as e:
                    print(e)
                    logger.exception(e)
                    print(f"{new_ip_list[i]} is not reachable")
                    return

        else:
            for i in range(len(ip_list)):
                try:
                    route_change.add_row([i + 1, ip_list[i], hop_info[ip_list[i]]['address'],
                                          new_ip_list[i], new_hop_info[new_ip_list[i]]['address']])
                except IndexError:
                    route_change.add_row([i + 1, ip_list[i], hop_info[ip_list[i]]['address'], "", ""])
        print(ip_list)
        ip_list = new_ip_list
        print(ip_list)
        return route_change
    else:
        return "No Route Change"


def route_tests(hop_info, ip_list):
    ###
    # Gathers all Eero tests in path
    ###
    i = 1
    for ip in ip_list:
        try:
            if hop_info[ip]['router']['oui'] == "eero inc.":
                result = asyncio.run(EeroTests.single_eero_results(customer_id=hop_info[ip]['router']['url']))
                print(f"{i} -- {hop_info[ip]['address']} -- "
                      f"https://dashboard.eero.com/networks/{hop_info[ip]['router']['url']}\n"
                      f"{result}")
                i += 1
            else:
                print(f"{i} -- {hop_info[ip]['address']} does not have an Eero. No tests available.")
                i += 1

        except Exception as e:
            print(e)
            print(f"{ip} is not reachable")


def path_check(ip=None, user=None, pswd=None, port=None):
    ###
    # This function will check the path taken to the target MBU IPv6
    ###
    try:
        if ip is not None:  # If the user has specified an IPv6 address, make that the target
            target_ip = ip
        else:
            target_ip = ip_check()
        if target_ip == 0 or target_ip == '0':
            return
        ###
        # Prefix is the first section of the IPv6 address
        # If we have the prefix, we can ignore some of the traceroute
        ###
        prefix = str(target_ip.split(":")[0] + ":" + target_ip.split(":")[1])

        try:
            print(f"Running traceroute to {target_ip}")
            traceroute_hops = traceroute(target_ip)
        except Exception as e:
            print(f"\n{e}\n")
            print(f"Traceroute to {target_ip} failed.\n")
            return
        hop_info = {}
        print(f"Formatting traceroute output for {target_ip}")
        ip_list = hop_to_ip(traceroute_hops, prefix)
        ip_list = ip_format(ip_list)
        print(f"Gathering information for hops in traceroute to {target_ip}")
        i = 1
        fail = False
        while True:
            try:
                hop_info, fail = gather_route(ip_list, hop_info, user, pswd, port)
                break
            except Exception as e:
                print(f"\n{e}\n")
                print(f"Gathering information for hops in traceroute to {target_ip} failed.\n")
                i += 1
                if i <= 5:
                    print(f"Retrying...\n")
                    continue
                else:
                    print(f"Unable to reach {target_ip}.\n, check your connection and try again.")
                    return 1
        if fail:
            return
        while True:
            try:
                print("\n")
                print("What would you like to do?")
                print("1. Print all IPs")
                print("2. Print all Routers")
                print("3. Print all MBU Versions")
                print("4. MTR all IPs")
                print("5. Print full route information")
                print("6. Route Change Check")
                print("7. Print Eero Test Results")
                print("0. Exit")
                try:
                    choice = int(input("Choice: "))
                except ValueError:
                    print("Invalid Choice")
                    continue
                if choice == 1:
                    print("\n\n")
                    i = 1
                    table = PrettyTable(["Hop", "IP"])
                    for ip in hop_info:
                        table.add_row([i, ip])
                        i += 1
                    print(table)
                elif choice == 2:
                    print("\n\n")
                    i = 1
                    table = PrettyTable(["Num", "IP", "MAC", "OUI", "Serial", "URL"])
                    for hop in hop_info:
                        mac = hop_info[hop]['router']['mac']
                        oui = hop_info[hop]['router']['oui']
                        if oui == "eero inc.":
                            url, serial = EeroTests.search_by_mac(mac=mac)
                            if url == "Missing Network" or serial == "Missing Serial":
                                pass
                            else:
                                url = f"https://dashboard.eero.com/networks/" \
                                      f"{url}"
                        else:
                            url, serial = "N/A", "N/A"
                        table.add_row([i, hop, mac, oui, serial, url])
                        i += 1
                    print(table)

                elif choice == 3:
                    print("\n\n")
                    i = 1
                    table = PrettyTable(["Num", "IP", "Address", "MBU Version"])
                    for ip in hop_info:
                        table.add_row([i, ip, hop_info[ip]['address'], hop_info[ip]['version']])
                        i += 1
                    print(table)
                elif choice == 4:
                    print("\n\n")
                    mtr(ip_list, hop_info)
                elif choice == 5:
                    print("\n\n")
                    route_print(hop_info)
                elif choice == 6:
                    print(f"\n{route_change_check(target_ip, prefix, ip_list, hop_info)}")
                elif choice == 7:
                    route_tests(hop_info, ip_list)
                elif choice == 0:
                    print("Exiting...")
                    break
                else:
                    print("Invalid Choice")
            except ValueError:
                print("Invalid Choice")
    except Exception as e:
        logger.exception(e)
        print("Exiting...")


def single_site_check(user=None, pswd=None, port=None, check=True):  # Return 0 if exiting single site check
    ###
    # Single Site Check
    ###
    ip = ip_check()  # Prompt user for IP and check if valid IPv6
    if ip == 0 or ip == '0':  # Exit if user enters for IPv6
        return 0
    mac = "N/A"
    while True:
        try:
            user, pswd, port = cred_check(user, pswd, port, check)
            mac = get_mac(None, ip, user=user, pswd=pswd, port=port)  # Get MAC address of connected NIC on target MBU
            break
        except paramiko.ssh_exception.AuthenticationException:
            print("Error authenticating, please enter correct credentials")
            continue
    if mac == '\'':  # Value that is returned if no MAC is found
        url, serial, network_id, oui = "N/A", "N/A", "N/A", "N/A"
    else:
        oui = MacLookup().lookup(mac)
        if oui == "eero inc.":
            url, serial = EeroTests.search_by_mac(mac=mac)  # Search for Eero network from MAC address
            network_id = url  # Using both URL and network ID in later functions
        else:
            url, serial, network_id = "N/A", "N/A", "N/A"
    while True:
        try:
            ###
            # Single site menu
            ###
            print("\n")
            print("What would you like to do?")
            print("1. MAC Lookup")
            print("2. PTMP Check")
            print("3. Address Lookup")
            print("4. Print Eero Tests")
            print("5. Target Different Site")
            print("0. Exit")
            try:
                choice = int(input("Choice: "))
            except ValueError:
                print("Invalid Choice")
                continue
            if choice == 1:
                ###
                # Keeping target IP, but doing a new MAC lookup
                ###
                table = PrettyTable(["IP", "MAC", "OUI", "Serial", "URL"])  # PrettyTable for MAC lookup
                mac = get_mac(None, ip, user=user, pswd=pswd, port=port)
                if mac == '\'':  # Value that is returned if no MAC is found
                    table.add_row([ip, "None Found", "N/A", "N/A", "N/A"])
                    print(table)
                else:
                    oui = MacLookup().lookup(mac)
                    if oui == "eero inc.":
                        url, serial = EeroTests.search_by_mac(mac=mac)
                        if url == "Missing Network" or serial == "Missing Serial":
                            pass  # Do nothing if missing network or serial, just print
                        else:
                            network_id = url  # Update network ID if found
                            url = f"https://dashboard.eero.com/networks/" \
                                  f"{url}"
                    else:  # If not eero, set url and serial to N/A
                        url = "N/A"
                        serial = "N/A"
                    table.add_row([ip, mac, oui, serial, url])
                    print(table)
            elif choice == 2:
                ###
                # PTMP radio search for site that is not recorded in LinkView
                # Should be run on anchor or seed MBU IPv6
                ###
                print(f"{ptmp_check(None, ip, user=user, pswd=pswd, port=port)}")  # Print PTMP check PrettyTable
            elif choice == 3:
                ###
                # Address lookup for site
                # Useful in single site check if running an MTR test and need to know the address of an IPv6 address
                ###
                table = PrettyTable(["IP", "Address"])
                table.add_row([ip, get_address(None, ip, user=user, pswd=pswd, port=port)])
                print(table)
            elif choice == 4:
                ###
                # Print last 100 Eero tests for network, if oui is eero and network is found
                ###
                if oui != "eero inc.":
                    table = PrettyTable(["Eero Not Found"])
                    table.add_row(["No Tests Available"])
                else:
                    table = asyncio.run(EeroTests.single_eero_results(customer_id=network_id))
                print(table)
            elif choice == 5:
                ###
                # Target different site
                ###
                ip = ip_check()
                if ip == 0 or ip == '0':
                    return 0
                while True:
                    try:
                        user, pswd, port = cred_check(user, pswd, port, check)
                        mac = get_mac(None, ip, user=user, pswd=pswd,
                                      port=port)  # Get MAC address of connected NIC on target MBU
                        break
                    except paramiko.ssh_exception.AuthenticationException:
                        print("Error authenticating, please enter correct credentials")
                        continue
                if mac == '\'':  # Value that is returned if no MAC is found
                    url, serial, network_id, oui = "N/A", "N/A", "N/A", "N/A"
                else:
                    oui = MacLookup().lookup(mac)
                    if oui == "eero inc.":
                        url, serial = EeroTests.search_by_mac(mac=mac)
                        if url == "Missing Network" or serial == "Missing Serial":
                            network_id = "N/A"
                        else:
                            network_id = url
                    else:
                        url, serial, network_id = "N/A", "N/A", "N/A"
            elif choice == 0:
                print("Exiting...")
                break
            else:
                print("Invalid Choice")
        except Exception as err:
            logger.exception(err)
            continue


def main():
    ###
    # Program starts here
    ###
    user, pswd, port = None, None, None
    try:
        ###
        # We first check if there is a file called routers.json in the same directory as this program.
        #   The routers.json file contains the MAC addresses, Serial Numbers, and URLs of all Eero routers that are
        #   set up on the network.
        ###
        with open("routers.json", "r") as f:  # Check if routers.json exists and if date is older than 1 day
            routers = json.load(f)
            time = str(routers['date'])  # Get the last updated date from the json file
            time = time.format("%Y-%m-%d_%H:%M:%S")
            time = arrow.get(time, "YYYY-MM-DD_HH:mm:ss")
            if time <= arrow.now() - datetime.timedelta(days=1):
                ###
                # (Y/n)/(y/N) -- During prompts, the uppercase Y or N indicates the default choice.
                ###
                choice = input("Your Eero router list is older than 1 day. Would you like to update? (Y/n)")
                if choice == "N" or choice == "n":
                    print("Using old Eero router list...")
                else:
                    print("Updating Eero router list...")
                    ###
                    # asyncio.run because the function was designed to be async in case it is needed in the future
                    ###
                    asyncio.run(EeroTests.grab_eeros())
            else:
                pass
    ###
    # If there is no routers.json file, we offer to create one.
    ###
    except FileNotFoundError:
        print("No Eero router list found. Create new list?")
        while True:
            choice = input("(y/n): ")  # No default choice, no capitalization
            if choice == "Y" or choice == "y":
                print("Creating new Eero router list...")
                asyncio.run(EeroTests.grab_eeros())
                print("Done!")
                break
            elif choice == "n" or choice == "N":
                print("Starting program without Eero router list...")
                break
            else:
                print("Invalid Choice")
                continue
    except Exception as e:  # Rare case that router.json is corrupted
        redo = input("\n\n\tEero Router list is corrupted. Should we create a new list? (Y/n): ")
        if redo == "N" or redo == "n":
            print(f"\n{e}\n")
            print("Exiting...")
            sys.exit(102)
        else:
            os.remove("routers.json")
            asyncio.run(EeroTests.grab_eeros())
            print("Done!")
    first_run = True
    while True:
        if not first_run:  # Used to check if the program has run through the menu before, simple for formatting
            print("\n\n")
        else:
            first_run = False
        try:
            ###
            # Main Menu
            ###
            print("What would you like to do?")
            print("1. Single Site Check")
            print("2. Path Check")
            print("3. Eero Check")
            print("4. Check for program update")
            print("0. Exit")
            try:
                choice = int(input("Choice: "))
            except ValueError:
                print("Invalid Choice")
                continue
            if choice == 1:
                single_site_check(user=user, pswd=pswd, port=port, check=True)  # Functions for focusing on a single site
            elif choice == 2:
                path_check(user=user, pswd=pswd, port=port)  # Functions for focusing on all sites in a path
            elif choice == 3:
                EeroTests.main()  # Some extra functions for Eero
            elif choice == 4:  # Separate updater python file needed
                print("Almost there... Not quite ready yet.")
                # import auto_updater
                # auto_updater.main()
            elif choice == 0:
                print("Exiting...")
                break
            else:
                print("Invalid Choice")
        except ValueError:
            print("Invalid Choice")


if __name__ == '__main__':
    main()
