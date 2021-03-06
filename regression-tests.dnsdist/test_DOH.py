#!/usr/bin/env python
import base64
import dns
import clientsubnetoption
from dnsdisttests import DNSDistTest

import pycurl

#from hyper import HTTP20Connection
#from hyper.ssl_compat import SSLContext, PROTOCOL_TLSv1_2

class DNSDistDOHTest(DNSDistTest):

    @classmethod
    def getDOHGetURL(cls, baseurl, query, rawQuery=False):
        if rawQuery:
            wire = query
        else:
            wire = query.to_wire()
        param = base64.urlsafe_b64encode(wire).decode('UTF8').rstrip('=')
        return baseurl + "?dns=" + param

    @classmethod
    def openDOHConnection(cls, port, caFile, timeout=2.0):
        conn = pycurl.Curl()
        conn.setopt(pycurl.HTTP_VERSION, pycurl.CURL_HTTP_VERSION_2)

        conn.setopt(pycurl.HTTPHEADER, ["Content-type: application/dns-message",
                                         "Accept: application/dns-message"])
        return conn

    @classmethod
    def sendDOHQuery(cls, port, servername, baseurl, query, response=None, timeout=2.0, caFile=None, useQueue=True, rawQuery=False):
        url = cls.getDOHGetURL(baseurl, query, rawQuery)
        conn = cls.openDOHConnection(port, caFile=caFile, timeout=timeout)
        #conn.setopt(pycurl.VERBOSE, True)
        conn.setopt(pycurl.URL, url)
        conn.setopt(pycurl.RESOLVE, ["%s:%d:127.0.0.1" % (servername, port)])
        conn.setopt(pycurl.SSL_VERIFYPEER, 1)
        conn.setopt(pycurl.SSL_VERIFYHOST, 2)
        if caFile:
            conn.setopt(pycurl.CAINFO, caFile)

        if response:
            cls._toResponderQueue.put(response, True, timeout)

        receivedQuery = None
        message = None
        data = conn.perform_rb()
        rcode = conn.getinfo(pycurl.RESPONSE_CODE)
        if rcode == 200:
            message = dns.message.from_wire(data)

        if useQueue and not cls._fromResponderQueue.empty():
            receivedQuery = cls._fromResponderQueue.get(True, timeout)

        return (receivedQuery, message)

#     @classmethod
#     def openDOHConnection(cls, port, caFile, timeout=2.0):
#         sslctx = SSLContext(PROTOCOL_TLSv1_2)
#         sslctx.load_verify_locations(caFile)
#         return HTTP20Connection('127.0.0.1', port=port, secure=True, timeout=timeout, ssl_context=sslctx, force_proto='h2')

#     @classmethod
#     def sendDOHQueryOverConnection(cls, conn, baseurl, query, response=None, timeout=2.0):
#         url = cls.getDOHGetURL(baseurl, query)

#         if response:
#             cls._toResponderQueue.put(response, True, timeout)

#         conn.request('GET', url)

#     @classmethod
#     def recvDOHResponseOverConnection(cls, conn, useQueue=False, timeout=2.0):
#         message = None
#         data = conn.get_response()
#         if data:
#             data = data.read()
#             if data:
#                 message = dns.message.from_wire(data)

#         if useQueue and not cls._fromResponderQueue.empty():
#             receivedQuery = cls._fromResponderQueue.get(True, timeout)
#             return (receivedQuery, message)
#         else:
#             return message

class TestDOH(DNSDistDOHTest):

    _serverKey = 'server.key'
    _serverCert = 'server.chain'
    _serverName = 'tls.tests.dnsdist.org'
    _caCert = 'ca.pem'
    _dohServerPort = 8443
    _serverName = 'tls.tests.dnsdist.org'
    _dohBaseURL = ("https://%s:%d/" % (_serverName, _dohServerPort))
    _config_template = """
    newServer{address="127.0.0.1:%s"}
    addDOHLocal("127.0.0.1:%s", "%s", "%s", { "/" })

    addAction("drop.doh.tests.powerdns.com.", DropAction())
    addAction("refused.doh.tests.powerdns.com.", RCodeAction(DNSRCode.REFUSED))
    addAction("spoof.doh.tests.powerdns.com.", SpoofAction("1.2.3.4"))
    """
    _config_params = ['_testServerPort', '_dohServerPort', '_serverCert', '_serverKey']

    def testDOHSimple(self):
        """
        DOH: Simple query
        """
        name = 'simple.doh.tests.powerdns.com.'
        query = dns.message.make_query(name, 'A', 'IN', use_edns=False)
        query.id = 0
        expectedQuery = dns.message.make_query(name, 'A', 'IN', use_edns=True, payload=4096)
        expectedQuery.id = 0
        response = dns.message.make_response(query)
        rrset = dns.rrset.from_text(name,
                                    3600,
                                    dns.rdataclass.IN,
                                    dns.rdatatype.A,
                                    '127.0.0.1')
        response.answer.append(rrset)

        (receivedQuery, receivedResponse) = self.sendDOHQuery(self._dohServerPort, self._serverName, self._dohBaseURL, query, response=response, caFile=self._caCert)
        self.assertTrue(receivedQuery)
        self.assertTrue(receivedResponse)
        receivedQuery.id = expectedQuery.id
        self.assertEquals(expectedQuery, receivedQuery)
        self.checkQueryEDNSWithoutECS(expectedQuery, receivedQuery)
        self.assertEquals(response, receivedResponse)

    def testDOHExistingEDNS(self):
        """
        DOH: Existing EDNS
        """
        name = 'existing-edns.doh.tests.powerdns.com.'
        query = dns.message.make_query(name, 'A', 'IN', use_edns=True, payload=8192)
        query.id = 0
        response = dns.message.make_response(query)
        rrset = dns.rrset.from_text(name,
                                    3600,
                                    dns.rdataclass.IN,
                                    dns.rdatatype.A,
                                    '127.0.0.1')
        response.answer.append(rrset)

        (receivedQuery, receivedResponse) = self.sendDOHQuery(self._dohServerPort, self._serverName, self._dohBaseURL, query, response=response, caFile=self._caCert)
        self.assertTrue(receivedQuery)
        self.assertTrue(receivedResponse)
        receivedQuery.id = query.id
        self.assertEquals(query, receivedQuery)
        self.assertEquals(response, receivedResponse)
        self.checkQueryEDNSWithoutECS(query, receivedQuery)
        self.checkResponseEDNSWithoutECS(response, receivedResponse)

    def testDOHExistingECS(self):
        """
        DOH: Existing EDNS Client Subnet
        """
        name = 'existing-ecs.doh.tests.powerdns.com.'
        ecso = clientsubnetoption.ClientSubnetOption('1.2.3.4')
        rewrittenEcso = clientsubnetoption.ClientSubnetOption('127.0.0.1', 24)
        query = dns.message.make_query(name, 'A', 'IN', use_edns=True, payload=512, options=[ecso], want_dnssec=True)
        query.id = 0
        response = dns.message.make_response(query)
        response.use_edns(edns=True, payload=4096, options=[rewrittenEcso])
        rrset = dns.rrset.from_text(name,
                                    3600,
                                    dns.rdataclass.IN,
                                    dns.rdatatype.A,
                                    '127.0.0.1')
        response.answer.append(rrset)

        (receivedQuery, receivedResponse) = self.sendDOHQuery(self._dohServerPort, self._serverName, self._dohBaseURL, query, response=response, caFile=self._caCert)
        self.assertTrue(receivedQuery)
        self.assertTrue(receivedResponse)
        receivedQuery.id = query.id
        self.assertEquals(query, receivedQuery)
        self.assertEquals(response, receivedResponse)
        self.checkQueryEDNSWithECS(query, receivedQuery)
        self.checkResponseEDNSWithECS(response, receivedResponse)

    def testDropped(self):
        """
        DOH: Dropped query
        """
        name = 'drop.doh.tests.powerdns.com.'
        query = dns.message.make_query(name, 'A', 'IN')
        (_, receivedResponse) = self.sendDOHQuery(self._dohServerPort, self._serverName, self._dohBaseURL, caFile=self._caCert, query=query, response=None, useQueue=False)
        print(receivedResponse)
        self.assertEquals(receivedResponse, None)

    def testRefused(self):
        """
        DOH: Refused
        """
        name = 'refused.doh.tests.powerdns.com.'
        query = dns.message.make_query(name, 'A', 'IN')
        query.id = 0
        expectedResponse = dns.message.make_response(query)
        expectedResponse.set_rcode(dns.rcode.REFUSED)

        (_, receivedResponse) = self.sendDOHQuery(self._dohServerPort, self._serverName, self._dohBaseURL, caFile=self._caCert, query=query, response=None, useQueue=False)
        self.assertEquals(receivedResponse, expectedResponse)

    def testSpoof(self):
        """
        DOH: Spoofed
        """
        name = 'spoof.doh.tests.powerdns.com.'
        query = dns.message.make_query(name, 'A', 'IN')
        query.id = 0
        query.flags &= ~dns.flags.RD
        expectedResponse = dns.message.make_response(query)
        rrset = dns.rrset.from_text(name,
                                    3600,
                                    dns.rdataclass.IN,
                                    dns.rdatatype.A,
                                    '1.2.3.4')
        expectedResponse.answer.append(rrset)

        (_, receivedResponse) = self.sendDOHQuery(self._dohServerPort, self._serverName, self._dohBaseURL, caFile=self._caCert, query=query, response=None, useQueue=False)
        self.assertEquals(receivedResponse, expectedResponse)

    def testDOHInvalid(self):
        """
        DOH: Invalid query
        """
        name = 'invalid.doh.tests.powerdns.com.'
        invalidQuery = dns.message.make_query(name, 'A', 'IN', use_edns=False)
        invalidQuery.id = 0
        # first an invalid query
        invalidQuery = invalidQuery.to_wire()
        invalidQuery = invalidQuery[:-5]
        (_, receivedResponse) = self.sendDOHQuery(self._dohServerPort, self._serverName, self._dohBaseURL, caFile=self._caCert, query=invalidQuery, response=None, useQueue=False, rawQuery=True)
        self.assertEquals(receivedResponse, None)

        # and now a valid one
        query = dns.message.make_query(name, 'A', 'IN', use_edns=False)
        query.id = 0
        expectedQuery = dns.message.make_query(name, 'A', 'IN', use_edns=True, payload=4096)
        expectedQuery.id = 0
        response = dns.message.make_response(query)
        rrset = dns.rrset.from_text(name,
                                    3600,
                                    dns.rdataclass.IN,
                                    dns.rdatatype.A,
                                    '127.0.0.1')
        response.answer.append(rrset)
        (receivedQuery, receivedResponse) = self.sendDOHQuery(self._dohServerPort, self._serverName, self._dohBaseURL, query, response=response, caFile=self._caCert)
        self.assertTrue(receivedQuery)
        self.assertTrue(receivedResponse)
        receivedQuery.id = expectedQuery.id
        self.assertEquals(expectedQuery, receivedQuery)
        self.checkQueryEDNSWithoutECS(expectedQuery, receivedQuery)
        self.assertEquals(response, receivedResponse)

class TestDOHAddingECS(DNSDistDOHTest):

    _serverKey = 'server.key'
    _serverCert = 'server.chain'
    _serverName = 'tls.tests.dnsdist.org'
    _caCert = 'ca.pem'
    _dohServerPort = 8443
    _serverName = 'tls.tests.dnsdist.org'
    _dohBaseURL = ("https://%s:%d/" % (_serverName, _dohServerPort))
    _config_template = """
    newServer{address="127.0.0.1:%s", useClientSubnet=true}
    addDOHLocal("127.0.0.1:%s", "%s", "%s", { "/" })
    setECSOverride(true)
    """
    _config_params = ['_testServerPort', '_dohServerPort', '_serverCert', '_serverKey']

    def testDOHSimple(self):
        """
        DOH with ECS: Simple query
        """
        name = 'simple.doh-ecs.tests.powerdns.com.'
        query = dns.message.make_query(name, 'A', 'IN', use_edns=False)
        query.id = 0
        rewrittenEcso = clientsubnetoption.ClientSubnetOption('127.0.0.0', 24)
        expectedQuery = dns.message.make_query(name, 'A', 'IN', use_edns=True, payload=4096, options=[rewrittenEcso])
        response = dns.message.make_response(query)
        rrset = dns.rrset.from_text(name,
                                    3600,
                                    dns.rdataclass.IN,
                                    dns.rdatatype.A,
                                    '127.0.0.1')
        response.answer.append(rrset)

        (receivedQuery, receivedResponse) = self.sendDOHQuery(self._dohServerPort, self._serverName, self._dohBaseURL, query, response=response, caFile=self._caCert)
        self.assertTrue(receivedQuery)
        self.assertTrue(receivedResponse)
        expectedQuery.id = receivedQuery.id
        self.assertEquals(expectedQuery, receivedQuery)
        self.checkQueryEDNSWithECS(expectedQuery, receivedQuery)
        self.assertEquals(response, receivedResponse)
        self.checkResponseNoEDNS(response, receivedResponse)

    def testDOHExistingEDNS(self):
        """
        DOH with ECS: Existing EDNS
        """
        name = 'existing-edns.doh-ecs.tests.powerdns.com.'
        query = dns.message.make_query(name, 'A', 'IN', use_edns=True, payload=8192)
        query.id = 0
        rewrittenEcso = clientsubnetoption.ClientSubnetOption('127.0.0.0', 24)
        expectedQuery = dns.message.make_query(name, 'A', 'IN', use_edns=True, payload=8192, options=[rewrittenEcso])
        response = dns.message.make_response(query)
        rrset = dns.rrset.from_text(name,
                                    3600,
                                    dns.rdataclass.IN,
                                    dns.rdatatype.A,
                                    '127.0.0.1')
        response.answer.append(rrset)

        (receivedQuery, receivedResponse) = self.sendDOHQuery(self._dohServerPort, self._serverName, self._dohBaseURL, query, response=response, caFile=self._caCert)
        self.assertTrue(receivedQuery)
        self.assertTrue(receivedResponse)
        receivedQuery.id = expectedQuery.id
        self.assertEquals(expectedQuery, receivedQuery)
        self.assertEquals(response, receivedResponse)
        self.checkQueryEDNSWithECS(expectedQuery, receivedQuery)
        self.checkResponseEDNSWithoutECS(response, receivedResponse)

    def testDOHExistingECS(self):
        """
        DOH with ECS: Existing EDNS Client Subnet
        """
        name = 'existing-ecs.doh-ecs.tests.powerdns.com.'
        ecso = clientsubnetoption.ClientSubnetOption('1.2.3.4')
        rewrittenEcso = clientsubnetoption.ClientSubnetOption('127.0.0.0', 24)
        query = dns.message.make_query(name, 'A', 'IN', use_edns=True, payload=512, options=[ecso], want_dnssec=True)
        query.id = 0
        expectedQuery = dns.message.make_query(name, 'A', 'IN', use_edns=True, payload=512, options=[rewrittenEcso])
        response = dns.message.make_response(query)
        response.use_edns(edns=True, payload=4096, options=[rewrittenEcso])
        rrset = dns.rrset.from_text(name,
                                    3600,
                                    dns.rdataclass.IN,
                                    dns.rdatatype.A,
                                    '127.0.0.1')
        response.answer.append(rrset)

        (receivedQuery, receivedResponse) = self.sendDOHQuery(self._dohServerPort, self._serverName, self._dohBaseURL, query, response=response, caFile=self._caCert)
        self.assertTrue(receivedQuery)
        self.assertTrue(receivedResponse)
        receivedQuery.id = expectedQuery.id
        self.assertEquals(expectedQuery, receivedQuery)
        self.assertEquals(response, receivedResponse)
        self.checkQueryEDNSWithECS(expectedQuery, receivedQuery)
        self.checkResponseEDNSWithECS(response, receivedResponse)
